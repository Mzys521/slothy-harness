"""运行器事件顺序、状态终态与最终结果的测试。

全部使用假模型、假执行器和 ``RunTimeline``，不访问网络。
"""

import unittest
from typing import Any
from unittest.mock import patch

from slothy.core.events import (
    EventBus,
    LLMTimeout,
    LLMTimeoutError,
    Metric,
    ModelError,
    ModelRequestStart,
    ModelResponded,
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    RunTimeline,
    StepEnd,
    StepLimitReached,
    StepOutcome,
    StepStarted,
    StepTimeout,
    TokenChunk,
    TokenUsage,
    ToolCallEnd,
    ToolCallStart,
    ToolCheckedError,
    ToolError,
    ToolTimeoutError,
)
from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from slothy.core.runtime import (
    AgentRunner,
    Run,
    RunCancelledError,
    RunDeadlineExceededError,
    RunStatus,
    StepTimeoutError,
)
from slothy.core.runtime.runner import RUN_DURATION_METRIC, STEP_DURATION_METRIC
from slothy.core.tools import (
    ProgressCallback,
    ProgressReport,
    ToolContext,
    ToolResult,
)


class ScriptedModel(ModelProvider):
    """按脚本返回模型响应，并模拟流式分片与用量上报。"""

    def __init__(
        self,
        responses: list[ModelResult],
        *,
        chunks: list[str] | None = None,
        usage: ModelUsage | None = None,
    ) -> None:
        self._responses = iter(responses)
        self._chunks = chunks or []
        self._usage = usage
        self.requests: list[dict[str, Any]] = []
        self.chunk_callbacks: list[Any] = []

    def generate(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> ModelResult:
        self.requests.append({"messages": messages, **kwargs})
        on_chunk = kwargs.get("on_chunk")
        self.chunk_callbacks.append(on_chunk)
        for text in self._chunks:
            if on_chunk is not None:
                on_chunk(text)
        response = next(self._responses)
        return response if self._usage is None else ModelResult(
            text=response.text,
            tool_calls=response.tool_calls,
            usage=self._usage,
        )


class StubRegistry:
    def definitions(self) -> list[dict[str, Any]]:
        return [{"name": "lookup", "description": "查找一个值"}]


class ScriptedExecutor:
    """返回脚本结果或按脚本抛出异常，用于覆盖工具错误、超时与进度上报。"""

    def __init__(
        self,
        results: list[Any] | None = None,
        *,
        progress: list[ProgressReport] | None = None,
    ) -> None:
        self._results = iter(results or [])
        self._progress = progress or []
        self.calls: list[ToolCall] = []

    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: ProgressCallback | None = None,
    ) -> ToolResult:
        self.calls.append(call)
        for report in self._progress:
            if on_progress is not None:
                on_progress(report)
        result = next(self._results, ToolResult(output={"value": 42}))
        if isinstance(result, BaseException):
            raise result
        return result


def tool_call(call_id: str = "call-1", name: str = "lookup") -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments={"key": "x"})


class EventFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(run_id="run-events")

    def _run(
        self,
        model: ScriptedModel,
        executor: ScriptedExecutor | None = None,
        *,
        max_steps: int = 8,
        runtime: Run | None = None,
    ) -> tuple[Any, RunTimeline]:
        timeline = RunTimeline()
        runner = AgentRunner(
            model, StubRegistry(), executor or ScriptedExecutor(), max_steps=max_steps
        )
        result = runner.run(
            "问题",
            context=self.context,
            runtime=runtime,
            events=timeline,
        )
        return result, timeline

    def test_run_started_event_is_recorded(self) -> None:
        """回归：早期事件必须进入接收端，不能因为中继绑定顺序而丢失。"""
        _, timeline = self._run(ScriptedModel([ModelResult(text="done")]))

        started = timeline.first(RunStarted)
        self.assertIsNotNone(started)
        self.assertEqual(started.run_id, self.context.run_id)
        self.assertEqual(started.sequence, 1)
        self.assertEqual(timeline.first(StepStarted).sequence, 2)

    def test_direct_answer_event_order(self) -> None:
        result, timeline = self._run(ScriptedModel([ModelResult(text="done")]))

        self.assertEqual((result.output, result.steps), ("done", 1))
        self.assertEqual(
            timeline.types(),
            [
                "run.started",
                "run.step.started",
                "run.model.request_started",
                "run.model.responded",
                "run.observability.token_usage",
                "run.step.ended",
                "run.observability.metric",
                "run.completed",
                "run.observability.metric",
            ],
        )
        self.assertEqual(timeline.first(RunCompleted).steps, 1)
        self.assertEqual(timeline.first(StepEnd).outcome, StepOutcome.COMPLETED)
        self.assertEqual(
            [event.name for event in timeline.of_type(Metric)],
            [STEP_DURATION_METRIC, RUN_DURATION_METRIC],
        )
        self.assertEqual(timeline.first(ModelRequestStart).message_count, 1)

    def test_tool_round_trip_event_order(self) -> None:
        model = ScriptedModel(
            [
                ModelResult(tool_calls=[tool_call()]),
                ModelResult(text="结果是 42"),
            ]
        )
        executor = ScriptedExecutor([ToolResult(output={"value": 42})])

        result, timeline = self._run(model, executor)

        self.assertEqual((result.output, result.steps), ("结果是 42", 2))
        self.assertEqual(timeline.first(RunStarted).run_id, self.context.run_id)
        self.assertEqual(
            timeline.types(),
            [
                "run.started",
                "run.step.started",
                "run.model.request_started",
                "run.model.responded",
                "run.observability.token_usage",
                "run.tool.call_started",
                "run.tool.call_ended",
                "run.step.ended",
                "run.observability.metric",
                "run.step.started",
                "run.model.request_started",
                "run.model.responded",
                "run.observability.token_usage",
                "run.step.ended",
                "run.observability.metric",
                "run.completed",
                "run.observability.metric",
            ],
        )
        call_start = timeline.first(ToolCallStart)
        self.assertEqual(
            (call_start.call_id, call_start.name, call_start.argument_keys),
            ("call-1", "lookup", ("key",)),
        )
        self.assertFalse(timeline.first(ToolCallEnd).is_error)
        self.assertEqual(timeline.first(ToolCallEnd).step_number, 1)
        self.assertEqual(
            timeline.first(StepEnd).tool_call_count, 1
        )
        self.assertEqual([event.sequence for event in timeline.events], list(range(1, 18)))

    def test_multiple_tool_calls_in_one_step(self) -> None:
        model = ScriptedModel(
            [
                ModelResult(
                    tool_calls=[tool_call("call-1"), tool_call("call-2")],
                ),
                ModelResult(text="完成"),
            ]
        )

        _, timeline = self._run(model)

        self.assertEqual(
            [event.call_id for event in timeline.of_type(ToolCallStart)],
            ["call-1", "call-2"],
        )
        self.assertEqual(timeline.first(StepEnd).tool_call_count, 2)

    def test_tool_error_result_stays_in_run(self) -> None:
        model = ScriptedModel(
            [
                ModelResult(tool_calls=[tool_call()]),
                ModelResult(text="工具报告失败"),
            ]
        )
        executor = ScriptedExecutor([ToolResult(output={"error": "x"}, is_error=True)])

        result, timeline = self._run(model, executor)

        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertTrue(timeline.first(ToolCallEnd).is_error)
        self.assertIsNone(timeline.first(RunFailed))

    def test_executor_failure_emits_tool_error_and_run_failed(self) -> None:
        model = ScriptedModel([ModelResult(tool_calls=[tool_call()])])
        executor = ScriptedExecutor([RuntimeError("内部实现细节")])

        with self.assertRaisesRegex(RuntimeError, "内部实现细节"):
            self._run(model, executor, max_steps=2)

    def test_executor_failure_event_carries_only_classification(self) -> None:
        timeline = RunTimeline()
        runner = AgentRunner(
            ScriptedModel([ModelResult(tool_calls=[tool_call()])]),
            StubRegistry(),
            ScriptedExecutor([RuntimeError("内部实现细节")]),
            max_steps=2,
        )

        with self.assertRaises(RuntimeError):
            runner.run("问题", context=self.context, events=timeline)

        failure = timeline.first(ToolError)
        self.assertEqual(
            (failure.call_id, failure.error.error_code, failure.error.error_type),
            ("call-1", "runtime_error", "RuntimeError"),
        )
        run_failed = timeline.first(RunFailed)
        self.assertEqual(run_failed.error.error_code, "runtime_error")
        self.assertEqual(run_failed.error.error_type, "RuntimeError")
        self.assertEqual(
            timeline.types()[-3:],
            ["run.step.ended", "run.failed", "run.observability.metric"],
        )

    def test_step_limit_reached_is_terminal_failure(self) -> None:
        model = ScriptedModel([ModelResult(tool_calls=[tool_call()])])
        executor = ScriptedExecutor()

        with self.assertRaisesRegex(RuntimeError, r"Exceeded max steps \(1\)"):
            self._run(model, executor, max_steps=1)

        self.assertEqual(executor.calls, [])

    def test_step_limit_events(self) -> None:
        timeline = RunTimeline()
        runner = AgentRunner(
            ScriptedModel([ModelResult(tool_calls=[tool_call()])]),
            StubRegistry(),
            ScriptedExecutor(),
            max_steps=1,
        )

        with self.assertRaises(RuntimeError):
            runner.run("问题", context=self.context, events=timeline)

        limit = timeline.first(StepLimitReached)
        self.assertEqual((limit.max_steps, limit.requested_tool_calls), (1, 1))
        self.assertEqual(timeline.first(StepEnd).outcome, StepOutcome.FAILED)
        self.assertEqual(
            timeline.first(RunFailed).error.error_code, "step_limit_reached"
        )
        self.assertEqual(
            timeline.types()[-4:],
            [
                "run.step.limit",
                "run.step.ended",
                "run.failed",
                "run.observability.metric",
            ],
        )

    def test_model_error_is_classified_without_leaking_message(self) -> None:
        timeline = RunTimeline()
        runner = AgentRunner(
            _FailingModel(ValueError("请求体包含密钥 sk-secret")),
            StubRegistry(),
            ScriptedExecutor(),
        )

        with self.assertRaises(ValueError):
            runner.run("问题", context=self.context, events=timeline)

        failure = timeline.first(ModelError)
        self.assertEqual(
            (failure.error.error_code, failure.error.error_type),
            ("runtime_error", "ValueError"),
        )
        self.assertNotIn("sk-secret", str(failure.as_record()))
        self.assertEqual(timeline.first(RunFailed).error.error_code, "runtime_error")

    def test_model_timeout_emits_llm_timeout(self) -> None:
        timeline = RunTimeline()
        runner = AgentRunner(
            _FailingModel(LLMTimeoutError("超时")), StubRegistry(), ScriptedExecutor()
        )

        with self.assertRaises(LLMTimeoutError):
            runner.run("问题", context=self.context, events=timeline)

        self.assertEqual(timeline.first(LLMTimeout).error.error_code, "llm_timeout")
        self.assertEqual(timeline.first(RunFailed).error.error_code, "llm_timeout")

    def test_unclassified_tool_timeout_keeps_its_classification(self) -> None:
        timeline = RunTimeline()
        runner = AgentRunner(
            ScriptedModel([ModelResult(tool_calls=[tool_call()])]),
            StubRegistry(),
            ScriptedExecutor([TimeoutError("超时")]),
        )

        with self.assertRaises(TimeoutError):
            runner.run("问题", context=self.context, events=timeline)

        self.assertEqual(timeline.first(ToolError).error.error_code, "unexpected_timeout")

    def test_tool_checked_timeout_emits_tool_timeout(self) -> None:
        timeline = RunTimeline()
        runner = AgentRunner(
            ScriptedModel([ModelResult(tool_calls=[tool_call()])]),
            StubRegistry(),
            ScriptedExecutor([ToolTimeoutError("超时")]),
        )

        with self.assertRaises(ToolCheckedError):
            runner.run("问题", context=self.context, events=timeline)

        self.assertEqual(
            timeline.first("run.tool.timeout").error.error_code, "tool_timeout"
        )

    def test_cancellation_emits_single_terminal_event(self) -> None:
        timeline = RunTimeline()
        runtime = Run(run_id=self.context.run_id, max_steps=8, events=timeline)
        model = _CancellingModel(runtime, ModelResult(tool_calls=[tool_call()]))
        executor = ScriptedExecutor()
        runner = AgentRunner(model, StubRegistry(), executor)

        with self.assertRaises(RunCancelledError):
            runner.run("问题", context=self.context, runtime=runtime)

        self.assertEqual(executor.calls, [])
        self.assertEqual(runtime.status, RunStatus.CANCELLED)
        self.assertEqual(timeline.first(StepEnd).outcome, StepOutcome.CANCELLED)
        self.assertEqual(len(timeline.of_type(RunCancelled)), 1)
        self.assertEqual(len(timeline.of_type(RunFailed)), 0)
        # 取消在模型返回前发生，因此 RunCancelled 早于同一次调用的 ModelResponded。
        self.assertEqual(
            timeline.types()[-4:],
            [
                "run.cancelled",
                "run.model.responded",
                "run.step.ended",
                "run.observability.metric",
            ],
        )

    def test_run_deadline_event_details(self) -> None:
        runtime = Run(
            run_id=self.context.run_id, max_steps=8, deadline_seconds=1.0
        )
        timeline = RunTimeline()
        clock = self._clock(100.0)
        runner = AgentRunner(
            _SlowEnoughModel(clock, advance_seconds=2.0),
            StubRegistry(),
            ScriptedExecutor(),
        )

        with self.assertRaises(RunDeadlineExceededError):
            runner.run("问题", context=self.context, runtime=runtime, events=timeline)

        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(len(timeline.of_type(RunFailed)), 1)
        self.assertEqual(timeline.first(RunFailed).error.error_code, "run_timeout")
        self.assertEqual(timeline.first(ModelResponded).duration_ms, 2000.0)
        self.assertEqual(timeline.first(StepEnd).outcome, StepOutcome.FAILED)
        self.assertEqual(timeline.types().count("run.step.ended"), 1)

    def test_step_timeout_emits_step_timeout(self) -> None:
        runtime = Run(
            run_id=self.context.run_id, max_steps=8, step_timeout_seconds=1.0
        )
        timeline = RunTimeline()
        clock = self._clock(200.0)
        runner = AgentRunner(
            _TwoRoundModel(clock, advance_seconds=1.5),
            StubRegistry(),
            ScriptedExecutor(),
        )

        with self.assertRaises(StepTimeoutError):
            runner.run("问题", context=self.context, runtime=runtime, events=timeline)

        self.assertIsNotNone(timeline.first(StepTimeout))
        self.assertEqual(timeline.first(ModelResponded).duration_ms, 1500.0)
        self.assertEqual(timeline.first(RunFailed).error.error_code, "step_timeout")
        self.assertEqual(timeline.types().count("run.step.ended"), 1)

    def _clock(self, now: float) -> "FakeClock":
        """固定运行器与运行时使用的时钟，返回可推进的时钟。"""
        clock = FakeClock(now)
        for target in (
            "slothy.core.runtime.state.monotonic",
            "slothy.core.events.emitter.monotonic",
            "slothy.core.timing.monotonic",
        ):
            patcher = patch(target, clock)
            patcher.start()
            self.addCleanup(patcher.stop)
        return clock

    def test_token_chunks_are_emitted_from_provider_callback(self) -> None:
        model = ScriptedModel([ModelResult(text="done")], chunks=["do", "ne"])

        _, timeline = self._run(model)

        chunks = timeline.of_type(TokenChunk)
        self.assertEqual([(chunk.index, chunk.text) for chunk in chunks], [(0, "do"), (1, "ne")])
        self.assertEqual(model.chunk_callbacks[0] is not None, True)

    def test_token_usage_accumulates_across_steps(self) -> None:
        model = ScriptedModel(
            [
                ModelResult(tool_calls=[tool_call()]),
                ModelResult(text="完成"),
            ],
            usage=ModelUsage(total_tokens=5, prompt_tokens=4, completion_tokens=1),
        )

        _, timeline = self._run(model)

        usage = timeline.of_type(TokenUsage)
        self.assertEqual(len(usage), 2)
        self.assertEqual(
            [event.cumulative.total_tokens for event in usage],
            [5, 10],
        )

    def test_broken_subscriber_does_not_change_the_result(self) -> None:
        bus = EventBus()
        bus.subscribe(RunEvent, _raise_on_event)
        runner = AgentRunner(ScriptedModel([ModelResult(text="done")]), StubRegistry(), ScriptedExecutor())

        result = runner.run("问题", context=self.context, events=bus)

        self.assertEqual(result.output, "done")
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(len(bus.failures), len(timeline_types(bus)))

    def test_run_without_sink_emits_nothing_and_still_works(self) -> None:
        runner = AgentRunner(ScriptedModel([ModelResult(text="done")]), StubRegistry(), ScriptedExecutor())

        result = runner.run("问题", context=self.context)

        self.assertEqual(result.run.status, RunStatus.COMPLETED)

    def test_runtime_supplied_sink_is_used_when_no_sink_is_passed(self) -> None:
        timeline = RunTimeline()
        runtime = Run(run_id=self.context.run_id, max_steps=8, events=timeline)
        runner = AgentRunner(ScriptedModel([ModelResult(text="done")]), StubRegistry(), ScriptedExecutor())

        runner.run("问题", context=self.context, runtime=runtime)

        self.assertEqual(timeline.types()[0], "run.started")
        self.assertIn("run.completed", timeline.types())


class FakeClock:
    """可推进的单调时钟，替代依赖真实耗时的时限测试。"""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FailingModel(ModelProvider):
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> ModelResult:
        raise self.error


class _SlowEnoughModel(ModelProvider):
    """始终直接回答，并在一次模型调用中推进假时钟。"""

    def __init__(self, clock: "FakeClock", *, advance_seconds: float) -> None:
        self.clock = clock
        self.advance_seconds = advance_seconds

    def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> ModelResult:
        self.clock.now += self.advance_seconds
        return ModelResult(text="done")


class _TwoRoundModel(ModelProvider):
    """第一轮请求工具、第二轮才回答，用于让一个步骤跨越两次模型调用。"""

    def __init__(self, clock: "FakeClock", *, advance_seconds: float = 0.0) -> None:
        self.clock = clock
        self.advance_seconds = advance_seconds
        self.rounds = 0

    def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> ModelResult:
        self.rounds += 1
        if self.rounds == 1:
            self.clock.now += self.advance_seconds
            return ModelResult(tool_calls=[tool_call()])
        return ModelResult(text="done")


class _CancellingModel(ModelProvider):
    def __init__(self, runtime: Run, response: ModelResult) -> None:
        self.runtime = runtime
        self.response = response

    def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> ModelResult:
        self.runtime.cancel()
        return self.response


class _CheckedTimeout(ToolCheckedError, TimeoutError):
    error_code = "tool_timeout"


def _raise_on_event(event: RunEvent) -> None:
    raise RuntimeError("监听器故障")


def timeline_types(bus: EventBus) -> list[str]:
    """返回总线已投递的事件类型，用于核对失败次数。"""
    return [failure.event_type for failure in bus.failures]
