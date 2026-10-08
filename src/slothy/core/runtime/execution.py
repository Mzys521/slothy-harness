"""可恢复的编排游标；领域数据转换仍在 Context、Model 和 Tool 模块。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from slothy.core.context import ContextError
from slothy.core.context.conversation import add, restore
from slothy.core.model import ToolCall
from slothy.core.model.session import ModelSession
from slothy.core.policy.session import PolicySession
from slothy.core.tools.journal import ToolJournal
from slothy.core.tools.session import ToolSession

from .observation import RunObservation
from .runner_models import RunnerResult
from .snapshot import (
    InMemorySnapshotStore, RuntimeSnapshot, SnapshotConflictError, SnapshotError,
    count, json_copy,
)
from .state import (
    Run, RunCancelledError, RunStatus, RunStateError, RunSuspendedError, StepStatus,
)


class RunExecution:
    def __init__(self, runner, tool_context, events, state, *, restored=False):
        self.runner, self.tool_context, self.state = runner, tool_context, state
        self.observation = RunObservation(state, events)
        self.policy = PolicySession(
            state, runner.policy, self.observation.events, restored=restored,
        )
        if runner.snapshot_store is not None:
            self.store = runner.snapshot_store
        else:
            if not restored or state.run_id not in runner._snapshot_stores:
                runner._snapshot_stores[state.run_id] = InMemorySnapshotStore()
            self.store = runner._snapshot_stores[state.run_id]
        self.revision = 0
        self.snapshot_failed = False
        self.completed_checkpoint = False
        self.enabled = False
        self.conversation = None
        self.cursor = {"phase": "model", "response": None, "index": 0, "error": None}
        self.model = ModelSession(
            runner.model, self.observation.events, state.check_active,
            self.policy, self.save,
        )
        self.journal = ToolJournal(
            state.run_id, self.observation.events, self.save, self.wait_for_approval,
        )
        self.tools = ToolSession(
            runner.registry, runner.executor, self.policy.policy,
            self.observation.events, self.policy, self.journal,
        )
        state._checkpoint = self.cancelled_checkpoint

    @classmethod
    def start(cls, runner, user_input, context, runtime, events):
        state = runtime or Run(context.run_id, runner.max_steps, events=events)
        if state.run_id != context.run_id or state.max_steps != runner.max_steps:
            raise ValueError("运行时状态与当前执行上下文不匹配")
        runner.latest_snapshot = None
        execution = cls(runner, context, events, state)
        runner._current_run = state
        state.start()
        try:
            execution.conversation = add(
                user_input, window=runner.context, token_budget=runner.token_budget,
                events=execution.observation.events,
            )
            execution.model.request_options = execution.conversation.bind_request(
                execution.tools.definitions, context,
            )
            execution.enabled = execution.conversation.can_snapshot
            if runner.snapshot_store is not None and not execution.enabled:
                raise SnapshotError("Context must support snapshots for this store")
            execution.save()
            return execution
        except Exception as error:
            state.fail(error)
            execution.observation.run_finished()
            state._checkpoint = None
            raise

    @classmethod
    def restore(cls, runner, snapshot, context, events, approval):
        from slothy.core.tools.replay import ApprovalDecision

        if approval is not None and not isinstance(approval, ApprovalDecision):
            raise SnapshotError("approval must be a trusted ApprovalDecision")
        if not isinstance(snapshot, RuntimeSnapshot):
            raise SnapshotError("resume requires a RuntimeSnapshot")
        data = snapshot.to_dict()
        if snapshot.run_id != context.run_id:
            raise SnapshotConflictError("snapshot Run ID differs from context")
        state = Run.from_snapshot(data["run"], policy=runner.policy, events=events)
        execution = cls(runner, context, events, state, restored=True)
        previous = execution.store.load(state.run_id)
        if previous is not None and previous.revision != snapshot.revision:
            raise SnapshotConflictError("cannot resume a stale snapshot")
        if previous is not None and previous.to_dict() != snapshot.to_dict():
            raise SnapshotConflictError("snapshot differs from stored revision")
        execution.revision = previous.revision if previous is not None else 0
        try:
            execution.conversation = restore(
                data["context"], window=runner.context,
                events=execution.observation.events,
            )
            execution.model.request_options = execution.conversation.bind_request(
                execution.tools.definitions, context,
            )
        except (ContextError, TypeError, ValueError, KeyError) as error:
            raise SnapshotError("invalid Context snapshot or configuration") from error
        execution.policy.restore_state(data["policy"])
        execution.model.restore_state(data["model"])
        execution.journal.restore_state(data["tools"])
        execution.cursor = json_copy(data["cursor"])
        execution._validate_cursor()
        execution.tools.validate_recovery()
        execution.enabled = True
        if state.status is RunStatus.CANCELLED:
            raise SnapshotError("cancelled Run cannot be resumed")
        if execution.cursor["phase"] == "done":
            if state.status is not RunStatus.COMPLETED:
                raise SnapshotError("terminal failure cannot be resumed")
            if approval is not None:
                raise SnapshotConflictError("completed Run has no pending approval")
            runner._current_run = state
            execution.save()
            return execution
        if approval is not None:
            execution.journal.resolve(approval)
        runner._current_run = state
        state.resume(execution.cursor["phase"])
        execution.save()
        return execution

    def _validate_cursor(self):
        cursor = self.cursor
        if set(cursor) != {"phase", "response", "index", "error"} or (
            cursor["phase"] not in {
                "model", "tools", "round_end", "step_end", "final", "done",
            }
        ):
            raise SnapshotError("invalid execution cursor")
        index = count(cursor["index"], "tool cursor")
        if cursor["error"] is not None and (
            not isinstance(cursor["error"], str) or not cursor["error"]
        ):
            raise SnapshotError("invalid saved error classification")
        if cursor["error"] in {
            "run_cancelled", "run_timeout", "step_timeout", "step_limit_reached",
            "no_progress", "snapshot_error", "snapshot_conflict",
        }:
            raise SnapshotError("non-recoverable termination")
        response = cursor["response"]
        if response is not None:
            if not isinstance(response, dict) or set(response) != {
                "text", "tool_calls",
            }:
                raise SnapshotError("invalid saved model response")
            if not isinstance(response["text"], str) or not isinstance(
                response["tool_calls"], list,
            ):
                raise SnapshotError("invalid model response fields")
            ids = []
            for call in response["tool_calls"]:
                if not isinstance(call, dict) or set(call) != {
                    "call_id", "name", "arguments",
                }:
                    raise SnapshotError("invalid pending tool call")
                if any(not isinstance(call[key], str) or not call[key]
                       for key in ("call_id", "name")):
                    raise SnapshotError("invalid pending tool identity")
                if not isinstance(call["arguments"], dict):
                    raise SnapshotError("invalid pending tool arguments")
                ids.append(call["call_id"])
            if len(set(ids)) != len(ids) or index > len(ids):
                raise SnapshotError("duplicate tool IDs or invalid tool cursor")
        phase = cursor["phase"]
        if phase == "model" and (response is not None or index):
            raise SnapshotError("model cursor has an uncommitted response")
        if phase in {"tools", "round_end", "step_end", "final", "done"} and (
            response is None or self.state.current_step is None
        ):
            raise SnapshotError("execution cursor has no current response")
        step = self.state.current_step
        if self.state.status is RunStatus.IDLE or (
            self.state.status is RunStatus.COMPLETED and phase != "done"
        ) or (
            self.state.status is RunStatus.WAITING_APPROVAL and phase != "tools"
        ):
            raise SnapshotError("Run state differs from execution phase")
        for record in self.journal.records.values():
            number = record["step"]
            if number > len(self.state.steps) or (
                record["call_id"] not in self.state.steps[number - 1].tool_call_ids
            ) or (
                number < len(self.state.steps) and record["status"] != "completed"
            ):
                raise SnapshotError("tool record differs from step history")
        committed = []
        if phase in {"tools", "round_end", "step_end"}:
            if not response["tool_calls"]:
                raise SnapshotError("tool cursor has no calls")
            if phase != "tools" and index != len(response["tool_calls"]):
                raise SnapshotError("unfinished tool batch at step boundary")
            calls = response["tool_calls"]
            ids = [call["call_id"] for call in calls]
            for record in self.journal.records.values():
                if record["step"] == step.number and (
                    {"call_id": record["call_id"], "name": record["name"],
                     "arguments": record["arguments"]} not in calls
                ):
                    raise SnapshotError("tool request differs from model response")
            entered = step.tool_call_ids
            if entered != ids[:len(entered)] or not (
                index <= len(entered) <= min(index + 1, len(ids))
            ):
                raise SnapshotError("step tool IDs differ from batch cursor")
            for saved_call in calls[:index]:
                call = ToolCall(**saved_call)
                identity = self.journal.completed_identity(call, step.number)
                if identity is None:
                    raise SnapshotError("committed tool result is missing")
                committed.append((call, self.journal.cached(identity)))
            try:
                self.conversation.validate_pending_exchange(
                    response, index,
                    [result.to_model_output() for _, result in committed],
                )
            except ContextError as error:
                raise SnapshotError("Context differs from tool cursor") from error
        elif phase in {"final", "done"}:
            if response["tool_calls"] or index or step.tool_call_ids:
                raise SnapshotError("final answer has pending tools")
            if phase == "done" and (
                self.state.status is not RunStatus.COMPLETED
                or step.status is not StepStatus.COMPLETED
            ):
                raise SnapshotError("terminal failure cannot be resumed")
            try:
                self.conversation.validate_pending_exchange(response, 0, [])
            except ContextError as error:
                raise SnapshotError("Context differs from final answer") from error
        elif step is not None and step.status is not StepStatus.COMPLETED and (
            step.tool_call_ids
        ):
            raise SnapshotError("model cursor has entered tools")
        pending = self.journal.pending_approval
        if pending is not None and (
            phase != "tools" or index >= len(response["tool_calls"])
            or pending.step_number != step.number
            or pending.call_id != response["tool_calls"][index]["call_id"]
        ):
            raise SnapshotError("approval differs from active tool cursor")
        self.policy.validate_round(committed if phase in {"tools", "round_end"} else [])

    @classmethod
    def cancel_saved(cls, runner, snapshot, context, events):
        execution = cls.restore(runner, snapshot, context, events, None)
        if execution.state.status is RunStatus.COMPLETED:
            execution.state._checkpoint = None
            return execution.result()
        execution.state.cancel()
        try:
            execution.state.check_active()
        except RunCancelledError:
            pass
        execution.cursor.update(phase="done", error="run_cancelled")
        execution.observation.run_finished()
        execution.save()
        execution.state._checkpoint = None
        return execution.result()

    def save(self):
        if not self.enabled:
            return
        try:
            snapshot = RuntimeSnapshot({
                "version": RuntimeSnapshot.VERSION, "revision": self.revision,
                "run": self.state.snapshot_state(),
                "context": self.conversation.snapshot_state(), "cursor": self.cursor,
                "tools": self.journal.snapshot_state(),
                "policy": self.policy.snapshot_state(),
                "model": self.model.snapshot_state(),
            })
            saved = self.store.save(snapshot, expected_revision=self.revision)
            if (
                not isinstance(saved, RuntimeSnapshot)
                or saved.run_id != snapshot.run_id
                or saved.revision != self.revision + 1
            ):
                raise SnapshotError("snapshot store returned an invalid revision")
        except SnapshotError:
            self.snapshot_failed = True
            raise
        except Exception as error:
            self.snapshot_failed = True
            raise SnapshotError("snapshot store failed") from error
        self.revision = saved.revision
        self.state.latest_snapshot = saved
        self.runner.latest_snapshot = saved

    def wait_for_approval(self, request):
        if not self.enabled:
            raise SnapshotError("approval waiting requires a snapshot-capable Context")
        self.state.suspend(approval=True)
        self.save()
        self.state.check_active()
        raise AssertionError("approval wait must suspend execution")

    def cancelled_checkpoint(self):
        step = self.state.current_step
        if step is None or step.status is not StepStatus.RUNNING:
            self.observation.run_finished()
            self.state._checkpoint = None
        self.save()

    def result(self):
        response = self.cursor["response"]
        return RunnerResult(
            output=response["text"] if self.state.status is RunStatus.COMPLETED else "",
            steps=len(self.state.steps), run=self.state,
            snapshot=self.state.latest_snapshot,
            approval=self.journal.pending_approval,
        )

    def drive(self):
        state, observation = self.state, self.observation
        if self.cursor["phase"] == "done":
            state._checkpoint = None
            return self.result()
        try:
            definitions = self.tools.definitions
            while True:
                self.policy.should_terminate()
                phase = self.cursor["phase"]
                if phase == "model":
                    if state.current_step is None or (
                        state.current_step.status is StepStatus.COMPLETED
                    ):
                        state.begin_step(len(state.steps) + 1)
                    self.save()
                    response = self.model.model_call(
                        self.conversation.get_windowed_messages(), definitions,
                    )
                    self.policy.should_terminate(len(response.tool_calls))
                    add(response, self.conversation)
                    self.cursor.update(
                        response={"text": response.text or "", "tool_calls": [
                            asdict(call) for call in response.tool_calls
                        ]}, index=0,
                        phase="tools" if response.tool_calls else "final", error=None,
                    )
                    self._validate_cursor()
                    if response.tool_calls:
                        state.wait_for_tool()
                    self.save()
                elif phase == "tools":
                    response = self.cursor["response"]
                    if self.cursor["index"] == len(response["tool_calls"]):
                        self.cursor["phase"] = "round_end"
                        self.save()
                        continue
                    call = ToolCall(**deepcopy(
                        response["tool_calls"][self.cursor["index"]],
                    ))
                    if call.call_id in state.current_step.tool_call_ids:
                        state.reenter_tool_call(call.call_id)
                    else:
                        state.begin_tool_call(call.call_id)
                    result = self.tools.tool_call(call, self.tool_context)
                    state.check_active()
                    add(result, self.conversation, call_id=call.call_id)
                    self.policy.record_tool_result(call, result)
                    self.cursor["index"] += 1
                    state.wait_for_tool()
                    self.save()
                elif phase == "round_end":
                    self.policy.finish_round(on_committed=self.round_committed)
                elif phase == "step_end":
                    if state.current_step.status is not StepStatus.COMPLETED:
                        state.finish_step()
                        observation.step_finished()
                    self.cursor.update(phase="model", response=None, index=0)
                    self.save()
                elif phase == "final":
                    if state.current_step.status is not StepStatus.COMPLETED:
                        state.finish_step()
                        observation.step_finished()
                    state.complete()
                    self.cursor["phase"] = "done"
                    observation.run_finished()
                    self.save()
                    self.completed_checkpoint = True
                    return self.result()
                else:
                    raise SnapshotError("unexpected execution phase")
        except RunSuspendedError:
            self.save()
            return self.result()
        except Exception as error:
            state.fail(error)
            self.cursor["error"] = getattr(error, "error_code", "runtime_error")
            if isinstance(error, RunStateError):
                self.cursor["phase"] = "done"
            if not isinstance(error, SnapshotError):
                self.save()
            raise
        finally:
            observation.run_finished()
            if state.status in {
                RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED,
            }:
                state._checkpoint = None
                if not self.snapshot_failed and not self.completed_checkpoint:
                    self.save()

    def round_committed(self):
        self.cursor["phase"] = "step_end"
        self.save()
