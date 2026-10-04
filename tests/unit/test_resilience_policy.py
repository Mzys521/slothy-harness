"""运行策略的终止、重试、安全和兼容契约；使用假时钟与假外部调用。"""

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from slothy.core.events import (
    LLMTimeoutError, ModelError, ModelRequestStart, PolicyTriggered,
    RunFailed, RunTimeline, TokenChunk, TokenUsage, ToolCallEnd, ToolCallStart,
    ToolProgress, ToolTimeout, ToolTimeoutError,
)
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import (
    DefaultPolicy, Policy, PolicyVerdict, RetryPolicy, SafetyPolicy,
    TimeoutPolicy, ToolNameRule,
)
from slothy.core.runtime import (
    AgentRunner, NoProgressError, Run, RunCancelledError,
    RunDeadlineExceededError, RunStatus, StepLimitExceededError,
)
from slothy.core.tools import ProgressReport, ToolContext, ToolResult


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Registry:
    def __init__(self, timeout=None):
        self.timeout = timeout

    def definitions(self):
        return [{"name": "lookup"}]

    def get_tool(self, name):
        return SimpleNamespace(timeout_seconds=self.timeout)


class Model(ModelProvider):
    def __init__(self, action):
        self.action = action
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(kwargs)
        return self.action(len(self.requests), kwargs)


class Executor:
    def __init__(self, action=None):
        self.action = action
        self.contexts = []

    def execute(self, call, context, on_progress=None):
        self.contexts.append(context)
        if self.action is not None:
            return self.action(call, context, on_progress)
        return ToolResult(output=42)


def call_response(number, argument=1):
    return ModelResult(tool_calls=[ToolCall(
        f"call-{number}", "lookup", {"argument": argument},
    )])


class ResiliencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.patches = ExitStack()
        for target in (
            "slothy.core.runtime.state.monotonic",
            "slothy.core.events.emitter.monotonic",
            "slothy.core.timing.monotonic",
        ):
            self.patches.enter_context(patch(target, self.clock))
        self.addCleanup(self.patches.close)
        self.timeline = RunTimeline()

    def runner(self, model, policy, executor=None, registry=None):
        return AgentRunner(
            model, registry or Registry(), executor or Executor(), policy=policy,
        )

    def run_runner(self, runner, runtime=None):
        return runner.run(
            "test", context=ToolContext("run-policy"),
            runtime=runtime, events=self.timeline,
        )

    def test_same_runner_supports_five_and_twenty_rounds(self):
        for maximum in (5, 20):
            with self.subTest(maximum=maximum):
                model = Model(lambda number, _: call_response(number))
                executor = Executor()
                runner = self.runner(model, DefaultPolicy(maximum), executor)
                with self.assertRaises(StepLimitExceededError):
                    self.run_runner(runner)
                self.assertEqual(len(model.requests), maximum)
                self.assertEqual(len(executor.contexts), maximum - 1)

    def test_twenty_rounds_thirty_second_deadline(self):
        def action(number, _):
            self.clock.advance(10)
            return call_response(number)

        policy = TimeoutPolicy(DefaultPolicy(20), timeout_seconds=30)
        model, executor = Model(action), Executor()
        runtime = Run("run-policy", max_steps=20)
        with self.assertRaises(RunDeadlineExceededError):
            self.run_runner(self.runner(model, policy, executor), runtime)

        self.assertEqual(len(model.requests), 3)
        self.assertEqual(len(executor.contexts), 2)
        self.assertEqual([item["timeout"] for item in model.requests], [30, 20, 10])
        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.deadline_seconds, 30)
        self.assertEqual(self.timeline.first(RunFailed).error.error_code, "run_timeout")

    def test_final_round_can_answer_without_tools(self):
        result = self.run_runner(self.runner(
            Model(lambda *_: ModelResult(text="done")), DefaultPolicy(1),
        ))
        self.assertEqual((result.steps, result.output), (1, "done"))

    def test_model_failure_retries_within_one_step(self):
        def action(number, _):
            if number < 3:
                raise ConnectionError("private provider detail")
            return ModelResult(text="done")

        result = self.run_runner(self.runner(Model(action), RetryPolicy(max_retries=2)))
        self.assertEqual(result.steps, 1)
        self.assertEqual(len(self.timeline.of_type(ModelRequestStart)), 3)
        self.assertEqual(len(self.timeline.of_type(ModelError)), 2)
        self.assertEqual(len(self.timeline.of_type(TokenUsage)), 1)
        self.assertEqual(len(self.timeline.of_type(RunFailed)), 0)
        self.assertEqual(len(self.timeline.of_type(PolicyTriggered)), 2)

    def test_retry_exhaustion_preserves_original_error(self):
        original = ConnectionError("private failure")

        def action(*_):
            raise original

        model = Model(action)
        with self.assertRaises(ConnectionError) as raised:
            self.run_runner(self.runner(model, RetryPolicy(max_retries=1)))
        self.assertIs(raised.exception, original)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(len(self.timeline.of_type(RunFailed)), 1)
        self.assertNotIn("private failure", str([
            event.as_record() for event in self.timeline.events
        ]))

    def test_permanent_failure_is_not_retried(self):
        def action(*_):
            raise ValueError("invalid response")

        model = Model(action)
        with self.assertRaises(ValueError):
            self.run_runner(self.runner(model, RetryPolicy()))
        self.assertEqual(len(model.requests), 1)

    def test_model_retry_keeps_original_messages_and_definitions(self):
        requests = []

        class MutatingModel(ModelProvider):
            def generate(self, messages, **kwargs):
                requests.append(messages[0]["content"])
                self_tool = kwargs["tools"][0]
                tool_name = self_tool["name"]
                if len(requests) == 1:
                    messages[0]["content"] = "mutated"
                    self_tool["name"] = "mutated"
                    raise ConnectionError("temporary")
                return ModelResult(text=tool_name)

        result = self.run_runner(self.runner(MutatingModel(), RetryPolicy()))
        self.assertEqual(requests, ["test", "test"])
        self.assertEqual(result.output, "lookup")

    def test_tool_retry_keeps_original_arguments(self):
        arguments = []

        def action(call, *_):
            arguments.append(call.arguments["argument"])
            if len(arguments) == 1:
                call.arguments["argument"] = 999
                raise ConnectionError("temporary")
            return ToolResult(output=42)

        model = Model(lambda number, _: (
            call_response(number) if number == 1 else ModelResult(text="done")
        ))
        self.run_runner(self.runner(
            model, RetryPolicy(retry_tools=frozenset({"lookup"})), Executor(action),
        ))
        self.assertEqual(arguments, [1, 1])

    def test_deadline_during_failure_prevents_retry(self):
        def action(*_):
            self.clock.advance(31)
            raise ConnectionError("failure")

        model = Model(action)
        policy = RetryPolicy(TimeoutPolicy(DefaultPolicy(20), timeout_seconds=30))
        with self.assertRaises(RunDeadlineExceededError):
            self.run_runner(self.runner(model, policy))
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(len(self.timeline.of_type(PolicyTriggered)), 0)

    def test_cancel_during_failure_prevents_retry(self):
        runtime = Run("run-policy", max_steps=8)

        def action(*_):
            runtime.cancel()
            raise ConnectionError("failure")

        model = Model(action)
        with self.assertRaises(RunCancelledError):
            self.run_runner(self.runner(model, RetryPolicy()), runtime)
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(runtime.status, RunStatus.CANCELLED)

    def test_streamed_failure_cannot_duplicate_text_and_old_callback_expires(self):
        callbacks = []

        def action(_, options):
            callbacks.append(options["on_chunk"])
            options["on_chunk"]("partial")
            raise ConnectionError("failure")

        model = Model(action)
        with self.assertRaises(ConnectionError):
            self.run_runner(self.runner(model, RetryPolicy()))
        callbacks[0]("late")
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(
            [e.text for e in self.timeline.of_type(TokenChunk)], ["partial"],
        )

    def test_tool_retry_requires_explicit_idempotent_allowlist(self):
        for retry_tools, expected in ((frozenset(), 1), (frozenset({"lookup"}), 3)):
            with self.subTest(retry_tools=retry_tools):
                def action(*_):
                    raise ToolTimeoutError("failed")

                executor = Executor(action)
                model = Model(lambda number, _: call_response(number))
                policy = RetryPolicy(retry_tools=retry_tools)
                with self.assertRaises(ToolTimeoutError):
                    self.run_runner(self.runner(model, policy, executor))
                self.assertEqual(len(executor.contexts), expected)

    def test_successful_tool_retry_has_one_start_and_one_result(self):
        callbacks = []

        def action(call, context, on_progress):
            if callbacks:
                callbacks[0](ProgressReport(completed=99))
            callbacks.append(on_progress)
            if len(callbacks) == 1:
                raise ConnectionError("temporary")
            on_progress(ProgressReport(completed=1))
            return ToolResult(output=42)

        model = Model(lambda number, _: (
            call_response(number) if number == 1 else ModelResult(text="done")
        ))
        result = self.run_runner(self.runner(
            model, RetryPolicy(retry_tools=frozenset({"lookup"})), Executor(action),
        ))
        self.assertEqual(result.steps, 2)
        self.assertEqual(len(self.timeline.of_type(ToolCallStart)), 1)
        self.assertEqual(len(self.timeline.of_type(ToolCallEnd)), 1)
        self.assertEqual(
            [e.completed for e in self.timeline.of_type(ToolProgress)], [1],
        )

    def test_tool_timeout_is_enforced_and_passed_to_executor(self):
        def action(*_):
            self.clock.advance(3)
            return ToolResult(output=42)

        executor = Executor(action)
        policy = TimeoutPolicy(tool_timeout_seconds=2)
        with self.assertRaises(ToolTimeoutError):
            self.run_runner(self.runner(
                Model(lambda n, _: call_response(n)), policy, executor,
            ))
        self.assertEqual(executor.contexts[0].timeout_seconds, 2)
        self.assertEqual(len(self.timeline.of_type(ToolTimeout)), 1)
        self.assertEqual(len(self.timeline.of_type(ToolCallEnd)), 0)

    def test_declared_tool_timeout_is_shorter_than_policy_timeout(self):
        def action(*_):
            self.clock.advance(1.5)
            return ToolResult(output=42)

        executor = Executor(action)
        with self.assertRaises(ToolTimeoutError):
            self.run_runner(self.runner(
                Model(lambda n, _: call_response(n)),
                TimeoutPolicy(tool_timeout_seconds=5), executor, Registry(timeout=1),
            ))
        self.assertEqual(executor.contexts[0].timeout_seconds, 1)

    def test_retry_does_not_reset_call_budget(self):
        def action(number, _):
            self.clock.advance(0.75)
            if number == 1:
                raise ConnectionError("temporary")
            return ModelResult(text="too late")

        model = Model(action)
        with self.assertRaises(LLMTimeoutError):
            self.run_runner(self.runner(model, RetryPolicy(
                TimeoutPolicy(model_timeout_seconds=1), max_retries=1,
            )))
        self.assertEqual([e["timeout"] for e in model.requests], [1, 0.25])

    def test_no_progress_ignores_call_ids_and_ends_run(self):
        model = Model(lambda n, _: call_response(n))
        executor = Executor()
        with self.assertRaises(NoProgressError):
            self.run_runner(self.runner(
                model, SafetyPolicy(no_progress_limit=3), executor,
            ))
        self.assertEqual(len(model.requests), 3)
        self.assertEqual(len(executor.contexts), 3)
        self.assertEqual(self.timeline.first(RunFailed).error.error_code, "no_progress")

    def test_changed_results_are_progress(self):
        counter = iter(range(1, 8))
        executor = Executor(lambda *_: ToolResult(output=next(counter)))
        model = Model(lambda n, _: (
            call_response(n) if n < 7 else ModelResult(text="done")
        ))
        result = self.run_runner(self.runner(
            model, SafetyPolicy(no_progress_limit=2), executor,
        ))
        self.assertEqual(result.steps, 7)

    def test_safety_can_return_sanitized_tool_failure_to_model(self):
        def action(*_):
            raise ValueError("SECRET detail")

        model = Model(lambda n, _: (
            call_response(n) if n == 1 else ModelResult(text="done")
        ))
        result = self.run_runner(self.runner(
            model, SafetyPolicy(return_tool_errors=True), Executor(action),
        ))
        self.assertEqual(result.output, "done")
        self.assertTrue(self.timeline.first(ToolCallEnd).is_error)
        self.assertNotIn("SECRET", str([e.as_record() for e in self.timeline.events]))

    def test_safety_rules_block_without_executing_tool(self):
        policy = SafetyPolicy(rules=(ToolNameRule("lookup", PolicyVerdict.DENY),))
        executor = Executor()
        model = Model(lambda n, _: (
            call_response(n) if n == 1 else ModelResult(text="done")
        ))
        self.run_runner(self.runner(model, policy, executor))
        self.assertEqual(executor.contexts, [])
        self.assertTrue(self.timeline.first(ToolCallEnd).is_error)

    def test_policy_state_does_not_leak_between_runs(self):
        def action(number, _):
            return (
                ModelResult(text="done") if number in (3, 6)
                else call_response(number)
            )

        runner = self.runner(Model(action), SafetyPolicy(no_progress_limit=3))
        self.assertEqual(self.run_runner(runner).steps, 3)
        self.assertEqual(self.run_runner(runner).steps, 3)

    def test_configuration_validation_and_protocol(self):
        self.assertIsInstance(DefaultPolicy(), Policy)
        for steps in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                DefaultPolicy(steps)
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                TimeoutPolicy(timeout_seconds=timeout)
        with self.assertRaises(ValueError):
            RetryPolicy(max_retries=-1)
        with self.assertRaises(ValueError):
            RetryPolicy(retryable_errors=(int,))
        with self.assertRaises(ValueError):
            self.runner(
                Model(lambda *_: ModelResult()), SafetyPolicy(no_progress_limit=0),
            )
        with self.assertRaises(ValueError):
            AgentRunner(
                Model(lambda *_: ModelResult()), Registry(), Executor(),
                max_steps=5, policy=DefaultPolicy(20),
            )

    def test_cooperative_deadline_waits_for_blocking_call_to_return(self):
        def action(*_):
            self.clock.advance(45)
            return ModelResult(text="late")

        runtime = Run("run-policy", max_steps=20)
        runner = self.runner(
            Model(action), TimeoutPolicy(DefaultPolicy(20), timeout_seconds=30),
        )
        with self.assertRaises(RunDeadlineExceededError):
            self.run_runner(runner, runtime)
        self.assertEqual(runtime.duration_ms, 45000)
        self.assertEqual(len(self.timeline.of_type(TokenUsage)), 0)


if __name__ == "__main__":
    unittest.main()
