"""快照恢复与工具重放安全；所有工具、校验器和时钟均为替身。"""

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from slothy.core.events import (
    EventBus, RunLifecycleEvent, RunTimeline, RunFailed, RunResumed, TokenUsage,
    ToolApprovalRequested, ToolEvent, RunEvent,
)
from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from slothy.core.policy import DefaultPolicy, RetryPolicy, SafetyPolicy, TimeoutPolicy
from slothy.core.runtime import (
    AgentRunner, InMemorySnapshotStore, NoProgressError, Run,
    RunCancelledError, RunDeadlineExceededError, RunStatus, RuntimeSnapshot,
    SnapshotConflictError, SnapshotError,
    StepStatus,
)
from slothy.core.tools import (
    ApprovalDecision, IdempotencyCheck, IdempotencyConflictError,
    ReplaySafety, ToolContext, ToolResult, VerificationStatus,
)


class Crash(BaseException):
    pass


class Registry:
    def __init__(self, safety=ReplaySafety.IDEMPOTENT):
        self.safety, self.version = safety, "1"

    def definitions(self):
        return [{"name": "work"}]

    def get_tool(self, name):
        return SimpleNamespace(
            replay_safety=self.safety, execution_version=self.version,
            timeout_seconds=None,
        )


class Model(ModelProvider):
    def __init__(self, calls=None):
        self.calls = calls or [ToolCall("call-1", "work", {"value": 1})]
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(messages)
        return ModelResult(
            text="done" if len(self.requests) > 1 else "",
            tool_calls=self.calls if len(self.requests) == 1 else [],
            usage=ModelUsage(total_tokens=1),
        )


class Executor:
    def __init__(self, action=None):
        self.calls, self.contexts, self.action = [], [], action

    def execute(self, call, context, on_progress=None):
        self.calls.append(call.call_id)
        self.contexts.append(context)
        return self.action(call, context) if self.action else ToolResult(output=42)


class VerifiedExecutor(Executor):
    def __init__(self, check, action=None):
        super().__init__(action)
        self.check = check
        self.verifications = []

    def verify_idempotency(self, call, context):
        self.verifications.append(context)
        return self.check(call, context)


class RuntimeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.context = ToolContext("run-snapshot")
        self.store = InMemorySnapshotStore()
        self.timeline = RunTimeline()

    def runner(self, executor, *, safety=ReplaySafety.IDEMPOTENT, model=None,
               policy=None, store=None, registry=None):
        return AgentRunner(
            model or Model(), registry or Registry(safety), executor,
            policy=policy or DefaultPolicy(), snapshot_store=store or self.store,
        )

    def run_runner(self, runner, runtime=None):
        return runner.run(
            "test", context=self.context, runtime=runtime, events=self.timeline,
        )

    def resume(self, runner, snapshot=None, approval=None):
        return runner.resume(
            snapshot or self.store.load(self.context.run_id), context=self.context,
            approval=approval, events=self.timeline,
        )

    def test_completed_tool_result_is_reused_after_interrupt(self):
        runtime = Run(self.context.run_id, 8)

        def interrupt(*_):
            runtime.interrupt()
            return ToolResult(output=42)

        executor, model = Executor(interrupt), Model()
        runner = self.runner(executor, model=model)
        paused = self.run_runner(runner, runtime)
        self.assertEqual(paused.run.status, RunStatus.SUSPENDED)
        sequence = self.timeline.events[-1].sequence
        result = self.resume(runner, paused.snapshot)
        self.assertEqual(result.output, "done")
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(runtime.status, RunStatus.SUSPENDED)
        self.assertEqual(executor.calls, ["call-1"])
        self.assertEqual(result.run.steps[0].tool_call_ids, ["call-1"])
        self.assertEqual([m["role"] for m in model.requests[1]], [
            "user", "assistant", "tool",
        ])
        self.assertEqual(self.timeline.first(RunResumed).sequence, sequence + 1)
        self.assertEqual(
            self.timeline.of_type(TokenUsage)[-1].cumulative.total_tokens, 2,
        )

    def test_batch_resume_skips_completed_prefix(self):
        runtime = Run(self.context.run_id, 8)

        def action(call, _):
            if call.call_id == "first":
                runtime.interrupt()
            return ToolResult(output=call.call_id)

        model = Model([
            ToolCall("first", "work", {"value": 1}),
            ToolCall("second", "work", {"value": 2}),
        ])
        executor = Executor(action)
        runner = self.runner(executor, model=model)
        paused = self.run_runner(runner, runtime)
        self.assertEqual(executor.calls, ["first"])
        result = self.resume(runner, paused.snapshot)
        self.assertEqual(result.output, "done")
        self.assertEqual(executor.calls, ["first", "second"])
        self.assertEqual(
            [m["call_id"] for m in model.requests[1] if m["role"] == "tool"],
            ["first", "second"],
        )

    def test_inflight_idempotent_tool_can_resume(self):
        first = True

        def action(*_):
            nonlocal first
            if first:
                first = False
                raise Crash()
            return ToolResult(output=42)

        executor = Executor(action)
        runner = self.runner(executor)
        with self.assertRaises(Crash):
            self.run_runner(runner)
        snapshot = self.store.load(self.context.run_id)
        self.assertEqual(snapshot.to_dict()["tools"]["records"]["1:call-1"]["status"],
                         "executing")
        result = self.resume(runner, snapshot)
        self.assertEqual(result.output, "done")
        self.assertEqual(len(executor.calls), 2)
        record = result.snapshot.to_dict()["tools"]["records"]["1:call-1"]
        self.assertEqual(record["attempts"], 2)

    def test_general_idempotent_tool_retries_without_name_allowlist(self):
        executor = Executor()

        def action(*_):
            if len(executor.calls) == 1:
                raise ConnectionError("temporary")
            return ToolResult(output=42)

        executor.action = action
        result = self.run_runner(self.runner(executor, policy=RetryPolicy()))
        self.assertEqual(result.output, "done")
        self.assertEqual(len(executor.calls), 2)

    def test_unverifiable_tool_blocks_before_first_execution(self):
        executor, model = Executor(), Model()
        runner = self.runner(executor, safety=ReplaySafety.UNVERIFIABLE, model=model)
        waiting = self.run_runner(runner)
        self.assertEqual(waiting.run.status, RunStatus.WAITING_APPROVAL)
        self.assertEqual(executor.calls, [])
        self.assertEqual(len(model.requests), 1)
        again = self.resume(runner, waiting.snapshot)
        self.assertEqual(again.approval.request_id, waiting.approval.request_id)
        self.assertEqual(executor.calls, [])
        result = self.resume(runner, again.snapshot, ApprovalDecision(
            again.approval.request_id, True, "human",
        ))
        self.assertEqual(result.output, "done")
        self.assertEqual(executor.calls, ["call-1"])
        self.assertTrue(executor.contexts[0].approval_id)
        self.assertEqual(len(self.timeline.of_type(RunFailed)), 0)

    def test_denial_is_returned_to_model_without_execution(self):
        executor, model = Executor(), Model()
        runner = self.runner(executor, safety=ReplaySafety.UNVERIFIABLE, model=model)
        waiting = self.run_runner(runner)
        result = self.resume(runner, waiting.snapshot, ApprovalDecision(
            waiting.approval.request_id, False, "human",
        ))
        self.assertEqual(result.output, "done")
        self.assertEqual(executor.calls, [])
        self.assertIn('"is_error": true', model.requests[1][-1]["content"])

    def test_approval_is_per_attempt_and_old_decision_cannot_replay(self):
        executor = Executor()

        def action(*_):
            if len(executor.calls) == 1:
                raise ConnectionError("unknown execution")
            return ToolResult(output=42)

        executor.action = action
        runner = self.runner(
            executor, safety=ReplaySafety.UNVERIFIABLE, policy=RetryPolicy(),
        )
        first = self.run_runner(runner)
        decision = ApprovalDecision(first.approval.request_id, True, "human")
        second = self.resume(runner, first.snapshot, decision)
        self.assertEqual(second.run.status, RunStatus.WAITING_APPROVAL)
        self.assertEqual(second.approval.attempt, 2)
        self.assertNotEqual(first.approval.request_id, second.approval.request_id)
        with self.assertRaises(SnapshotConflictError):
            self.resume(runner, second.snapshot, decision)
        self.assertEqual(len(executor.calls), 1)
        result = self.resume(runner, second.snapshot, ApprovalDecision(
            second.approval.request_id, True, "human",
        ))
        self.assertEqual(result.output, "done")
        self.assertEqual(len(executor.calls), 2)

    def test_consumed_approval_is_not_restored_after_crash(self):
        executor = Executor(lambda *_: (_ for _ in ()).throw(Crash()))
        runner = self.runner(executor, safety=ReplaySafety.UNVERIFIABLE)
        waiting = self.run_runner(runner)
        decision = ApprovalDecision(waiting.approval.request_id, True, "human")
        with self.assertRaises(Crash):
            self.resume(runner, waiting.snapshot, decision)
        saved = self.store.load(self.context.run_id)
        again = self.resume(runner, saved)
        self.assertEqual(again.run.status, RunStatus.WAITING_APPROVAL)
        self.assertNotEqual(again.approval.request_id, decision.request_id)
        self.assertEqual(len(executor.calls), 1)

    def test_keyed_tool_reuses_verified_result_after_lost_response(self):
        applied = False

        def verify(*_):
            return IdempotencyCheck(
                VerificationStatus.COMPLETED, ToolResult(output=42),
            ) if applied else IdempotencyCheck(VerificationStatus.NOT_STARTED)

        def action(*_):
            nonlocal applied
            applied = True
            raise ConnectionError("response lost after side effect")

        executor = VerifiedExecutor(verify, action)
        result = self.run_runner(self.runner(
            executor, safety=ReplaySafety.KEYED, policy=RetryPolicy(),
        ))
        self.assertEqual(result.output, "done")
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(len(executor.verifications), 2)
        self.assertEqual(executor.verifications[0].idempotency_key,
                         executor.verifications[1].idempotency_key)
        self.assertTrue(executor.contexts[0].request_fingerprint)

    def test_keyed_unknown_or_missing_verifier_requires_approval(self):
        for executor in (Executor(), VerifiedExecutor(
            lambda *_: IdempotencyCheck(VerificationStatus.UNKNOWN),
        )):
            with self.subTest(executor=type(executor).__name__):
                runner = self.runner(
                    executor, safety=ReplaySafety.KEYED, store=InMemorySnapshotStore(),
                )
                waiting = self.run_runner(runner)
                self.assertEqual(waiting.run.status, RunStatus.WAITING_APPROVAL)
                self.assertEqual(executor.calls, [])

    def test_key_conflict_cannot_be_overridden_by_approval(self):
        def verify(*_):
            raise IdempotencyConflictError("key bound to other parameters")

        executor = VerifiedExecutor(verify)
        runner = self.runner(executor, safety=ReplaySafety.KEYED)
        with self.assertRaises(IdempotencyConflictError):
            self.run_runner(runner)
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.timeline.of_type(ToolApprovalRequested), ())

    def test_undeclared_tool_first_call_works_but_unknown_retry_blocks(self):
        executor = Executor(lambda *_: (_ for _ in ()).throw(ConnectionError()))
        result = self.run_runner(self.runner(
            executor, safety=ReplaySafety.UNSPECIFIED, policy=RetryPolicy(),
        ))
        self.assertEqual(result.run.status, RunStatus.WAITING_APPROVAL)
        self.assertEqual(result.approval.reason, "undeclared_replay")
        self.assertEqual(len(executor.calls), 1)

    def test_stale_snapshot_and_wrong_request_are_rejected_before_execution(self):
        executor = Executor()
        runner = self.runner(executor, safety=ReplaySafety.UNVERIFIABLE)
        waiting = self.run_runner(runner)
        with self.assertRaises(SnapshotConflictError):
            self.resume(runner, waiting.snapshot,
                        ApprovalDecision("wrong", True, "human"))
        again = self.resume(runner, waiting.snapshot)
        with self.assertRaises(SnapshotConflictError):
            self.resume(runner, waiting.snapshot, ApprovalDecision(
                waiting.approval.request_id, True, "human",
            ))
        self.assertEqual(executor.calls, [])
        self.assertGreater(again.snapshot.revision, waiting.snapshot.revision)

    def test_tool_version_change_rejects_replay(self):
        executor = Executor(lambda *_: (_ for _ in ()).throw(Crash()))
        registry = Registry()
        runner = self.runner(executor, registry=registry)
        with self.assertRaises(Crash):
            self.run_runner(runner)
        registry.version = "2"
        with self.assertRaises(SnapshotConflictError):
            self.resume(runner)
        self.assertEqual(len(executor.calls), 1)

    def test_version_change_does_not_consume_pending_approval(self):
        executor, registry = Executor(), Registry(ReplaySafety.UNVERIFIABLE)
        runner = self.runner(executor, registry=registry)
        waiting = self.run_runner(runner)
        registry.version = "2"
        with self.assertRaises(SnapshotConflictError):
            self.resume(runner, waiting.snapshot, ApprovalDecision(
                waiting.approval.request_id, True, "human",
            ))
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.store.load(self.context.run_id), waiting.snapshot)

    def test_completed_result_survives_tool_implementation_change(self):
        runtime = Run(self.context.run_id, 8)
        executor = Executor(lambda *_: (runtime.interrupt(), ToolResult(output=42))[1])
        registry = Registry()
        runner = self.runner(executor, registry=registry)
        paused = self.run_runner(runner, runtime)
        registry.version = "2"
        result = self.resume(runner, paused.snapshot)
        self.assertEqual(result.output, "done")
        self.assertEqual(len(executor.calls), 1)

    def test_snapshot_store_failure_prevents_tool_execution(self):
        class FailBeforeTool(InMemorySnapshotStore):
            def save(self, snapshot, *, expected_revision):
                if any(record["status"] == "executing" for record in
                       snapshot.to_dict()["tools"]["records"].values()):
                    raise SnapshotError("disk failed")
                return super().save(snapshot, expected_revision=expected_revision)

        executor = Executor()
        runner = self.runner(executor, store=FailBeforeTool(), policy=RetryPolicy())
        with self.assertRaises(SnapshotError):
            self.run_runner(runner)
        self.assertEqual(executor.calls, [])

    def test_snapshot_validation_and_copy_isolation(self):
        runner = self.runner(Executor(), safety=ReplaySafety.UNVERIFIABLE)
        waiting = self.run_runner(runner)
        copied = waiting.snapshot.to_dict()
        copied["run"]["run_id"] = "other"
        self.assertEqual(waiting.snapshot.run_id, self.context.run_id)
        for mutation in (
            lambda data: data.update(version=999),
            lambda data: data["cursor"].update(index=10),
            lambda data: data["tools"]["records"]["1:call-1"].update(key="forged"),
            lambda data: data["tools"]["records"]["1:call-1"].update(
                arguments={"value": 2},
            ),
            lambda data: data["run"]["steps"][0].update(call_ids=[]),
            lambda data: data["cursor"].update(phase="model"),
            lambda data: data["cursor"].update(phase="done"),
            lambda data: data["policy"].update(round=["forged"]),
        ):
            with self.subTest(mutation=mutation):
                data = waiting.snapshot.to_dict()
                mutation(data)
                with self.assertRaises(SnapshotError):
                    # 新存储用于测试数据校验，避免版本比较先拒绝篡改。
                    changed = RuntimeSnapshot.from_dict(data)
                    other = self.runner(Executor(), safety=ReplaySafety.UNVERIFIABLE,
                                        store=InMemorySnapshotStore())
                    self.resume(other, changed)
        with self.assertRaises(SnapshotError):
            RuntimeSnapshot.from_json('{"version":1,"version":1}')

    def test_completed_snapshot_returns_without_model_or_tool_calls(self):
        model, executor = Model(), Executor()
        runner = self.runner(executor, model=model)
        result = self.run_runner(runner)
        restored = self.resume(runner, result.snapshot)
        self.assertEqual(restored.output, "done")
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(len(executor.calls), 1)

    def test_cancelled_snapshot_cannot_resume(self):
        runtime = Run(self.context.run_id, 8)
        executor = Executor(lambda *_: (runtime.cancel(), ToolResult(output=42))[1])
        runner = self.runner(executor)
        with self.assertRaises(Exception):
            self.run_runner(runner, runtime)
        with self.assertRaises(SnapshotError):
            self.resume(runner)
        self.assertEqual(len(executor.calls), 1)

    def test_cancelling_waiting_run_invalidates_approval_snapshot(self):
        # 默认存储也要保留取消标记；旧的审批快照不能复活已取消任务。
        executor = Executor()
        runner = AgentRunner(Model(), Registry(ReplaySafety.UNVERIFIABLE), executor)
        waiting = self.run_runner(runner)
        waiting.run.cancel()
        self.assertEqual(waiting.run.current_step.status, StepStatus.CANCELLED)
        self.assertEqual(self.timeline.types()[-3:], [
            "run.cancelled", "run.step.ended", "run.observability.metric",
        ])
        self.assertEqual(waiting.run.latest_snapshot.to_dict()["run"]["status"],
                         RunStatus.CANCELLED.value)
        with self.assertRaises(SnapshotConflictError):
            self.resume(runner, waiting.snapshot, ApprovalDecision(
                waiting.approval.request_id, True, "human",
            ))
        with self.assertRaises(SnapshotError):
            self.resume(runner, waiting.run.latest_snapshot)
        self.assertEqual(executor.calls, [])

    def test_cancel_from_pause_observer_is_terminal(self):
        runtime = Run(self.context.run_id, 8)
        bus = EventBus()
        bus.subscribe(RunLifecycleEvent, lambda event: (
            runtime.cancel() if event.event_type == "run.suspended" else None
        ))
        executor = Executor()
        runner = self.runner(executor, safety=ReplaySafety.UNVERIFIABLE)
        with self.assertRaises(RunCancelledError):
            runner.run("test", context=self.context, runtime=runtime, events=bus)
        self.assertEqual(runtime.status, RunStatus.CANCELLED)
        self.assertEqual(runtime.current_step.status, StepStatus.CANCELLED)
        self.assertEqual(executor.calls, [])

    def test_recovery_events_support_category_subscriptions(self):
        bus = EventBus()
        lifecycle, tools = [], []
        bus.subscribe(RunLifecycleEvent, lifecycle.append)
        bus.subscribe(ToolEvent, tools.append)
        runner = self.runner(Executor(), safety=ReplaySafety.UNVERIFIABLE)
        waiting = runner.run("test", context=self.context, events=bus)
        self.assertIn("run.suspended", [event.event_type for event in lifecycle])
        self.assertIn("run.tool.approval_requested",
                      [event.event_type for event in tools])
        runner.resume(waiting.snapshot, context=self.context, events=bus,
                      approval=ApprovalDecision(waiting.approval.request_id,
                                                False, "human"))
        self.assertIn("run.resumed", [event.event_type for event in lifecycle])
        self.assertIn("run.tool.approval_resolved",
                      [event.event_type for event in tools])

    def test_model_failure_resumes_with_recorded_attempt_budget(self):
        class FailingModel(ModelProvider):
            def __init__(self):
                self.calls = 0

            def generate(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise Crash()
                raise ConnectionError("unavailable")

        model, executor = FailingModel(), Executor()
        runner = self.runner(executor, model=model, policy=RetryPolicy(max_retries=1))
        with self.assertRaises(Crash):
            self.run_runner(runner)
        saved = self.store.load(self.context.run_id).to_dict()
        self.assertEqual(saved["model"]["attempts"], 2)
        # 显式恢复允许一次新尝试，但不会重置自动重试计数。
        with self.assertRaises(ConnectionError):
            self.resume(runner)
        self.assertEqual(model.calls, 3)
        self.assertEqual(executor.calls, [])

    def test_recovery_rejects_context_result_that_differs_from_journal(self):
        runtime = Run(self.context.run_id, 8)

        def interrupt_after_progress(event):
            if event.event_type == "run.step.ended":
                runtime.interrupt()

        bus = EventBus()
        bus.subscribe(RunEvent, interrupt_after_progress)
        executor = Executor()
        runner = self.runner(executor)
        paused = runner.run("test", context=self.context, runtime=runtime, events=bus)
        self.assertEqual(paused.run.status, RunStatus.SUSPENDED)
        # 此时游标已进入下一次模型调用，改造为批次已提交边界以检查一致性。
        data = paused.snapshot.to_dict()
        first_response = data["context"]["active"][1]
        data["cursor"].update(
            phase="step_end", index=1,
            response={"text": first_response["content"],
                      "tool_calls": first_response["tool_calls"]},
        )
        data["context"]["active"][2]["content"] = "forged"
        other = self.runner(executor, store=InMemorySnapshotStore())
        with self.assertRaises(SnapshotError):
            self.resume(other, RuntimeSnapshot.from_dict(data))
        self.assertEqual(len(executor.calls), 1)

    def test_snapshot_preserves_budget_and_excludes_waiting_time(self):
        now = [0.0]
        runtime = Run(self.context.run_id, 8)

        def action(*_):
            now[0] += 1
            runtime.interrupt()
            return ToolResult(output=42)

        class TimedModel(Model):
            def generate(self, messages, **kwargs):
                if self.requests:
                    now[0] += 2
                return super().generate(messages, **kwargs)

        runner = self.runner(Executor(action), model=TimedModel(), policy=TimeoutPolicy(
            timeout_seconds=3,
        ))
        with ExitStack() as patches:
            for target in (
                "slothy.core.runtime.state.monotonic",
                "slothy.core.events.emitter.monotonic", "slothy.core.timing.monotonic",
            ):
                patches.enter_context(patch(target, lambda: now[0]))
            paused = self.run_runner(runner, runtime)
            now[0] += 100
            with self.assertRaises(RunDeadlineExceededError):
                self.resume(runner, paused.snapshot)
            elapsed = runner.latest_snapshot.to_dict()["run"]["elapsed_seconds"]
            self.assertEqual(elapsed, 3)

    def test_no_progress_state_survives_recovery(self):
        runtime = Run(self.context.run_id, 8)
        executor = Executor(lambda *_: (runtime.interrupt(), ToolResult(output=42))[1])

        class RepeatingModel(Model):
            def generate(self, messages, **kwargs):
                self.requests.append(messages)
                return ModelResult(tool_calls=[ToolCall(
                    f"call-{len(self.requests)}", "work", {"value": 1},
                )])

        model = RepeatingModel()
        runner = self.runner(
            executor, model=model, policy=SafetyPolicy(no_progress_limit=2),
        )
        paused = self.run_runner(runner, runtime)
        executor.action = None
        with self.assertRaises(NoProgressError):
            self.resume(runner, paused.snapshot)
        self.assertEqual(len(executor.calls), 2)
        saved = runner.latest_snapshot.to_dict()
        self.assertEqual(saved["run"]["no_progress_rounds"], 2)


if __name__ == "__main__":
    unittest.main()
