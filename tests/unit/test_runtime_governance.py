"""策略拦截、进度上报与上下文裁剪的事件测试。

使用假模型、假执行器和 ``RunTimeline``，不访问网络。
"""

import unittest
from typing import Any

from slothy.core.context import ContextWindow, MessageRole
from slothy.core.events import (
    ContextCompressed,
    GuardrailBlocked,
    PolicyTriggered,
    RunCompleted,
    RunTimeline,
    ToolCallEnd,
    ToolProgress,
)
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import AllowlistRule, PolicyEngine, PolicyVerdict, ToolNameRule
from slothy.core.runtime import AgentRunner, RunStatus
from slothy.core.tools import (
    ProgressCallback,
    ProgressReport,
    ToolContext,
    ToolResult,
)


class ScriptedModel(ModelProvider):
    """按脚本返回模型响应。"""

    def __init__(self, responses: list[ModelResult]) -> None:
        self._responses = iter(responses)
        self.requests: list[list[dict[str, Any]]] = []

    def generate(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> ModelResult:
        self.requests.append(list(messages))
        return next(self._responses)


class StubRegistry:
    def definitions(self) -> list[dict[str, Any]]:
        return [{"name": "lookup", "description": "查找一个值"}]


class ProgressExecutor:
    """在执行中上报进度的执行器。"""

    def __init__(self, reports: list[ProgressReport] | None = None) -> None:
        self.reports = reports or []
        self.calls: list[ToolCall] = []
        self.received_callback = False

    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: ProgressCallback | None = None,
    ) -> ToolResult:
        self.calls.append(call)
        self.received_callback = on_progress is not None
        for report in self.reports:
            if on_progress is not None:
                on_progress(report)
        return ToolResult(output={"value": 42})


class RecorderExecutor:
    """记录是否被调用的执行器，用于证明拦截时执行器不被调用。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: ProgressCallback | None = None,
    ) -> ToolResult:
        self.calls.append(call)
        return ToolResult(output={"value": 42})


def tool_call(name: str = "lookup", call_id: str = "call-1") -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments={"key": "x"})


class PolicyEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(run_id="run-policy")

    def _run(
        self,
        model: ScriptedModel,
        executor: Any,
        *,
        policy: PolicyEngine | None = None,
    ) -> tuple[Any, RunTimeline]:
        timeline = RunTimeline()
        runner = AgentRunner(
            model, StubRegistry(), executor, max_steps=4, policy=policy
        )
        result = runner.run("问题", context=self.context, events=timeline)
        return result, timeline

    def test_default_policy_allows_without_policy_events(self) -> None:
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
        )
        executor = RecorderExecutor()

        _, timeline = self._run(model, executor)

        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(timeline.of_type(PolicyTriggered), ())
        self.assertEqual(timeline.of_type(GuardrailBlocked), ())

    def test_deny_blocks_execution_and_returns_error_to_model(self) -> None:
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="被拦截了")]
        )
        executor = RecorderExecutor()
        policy = PolicyEngine(rules=(ToolNameRule("lookup", PolicyVerdict.DENY),))

        result, timeline = self._run(model, executor, policy=policy)

        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(executor.calls, [])
        triggered = timeline.first(PolicyTriggered)
        self.assertEqual((triggered.policy, triggered.decision), ("tool_name", "deny"))
        blocked = timeline.first(GuardrailBlocked)
        self.assertEqual((blocked.guardrail, blocked.call_id), ("tool_name", "call-1"))
        self.assertTrue(timeline.first(ToolCallEnd).is_error)
        follow_up = model.requests[-1][-1]
        self.assertEqual(follow_up["role"], "tool")
        self.assertIn("安全策略拦截", follow_up["content"])

    def test_ask_is_blocked_because_approval_is_not_implemented(self) -> None:
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
        )
        executor = RecorderExecutor()
        policy = PolicyEngine(rules=(ToolNameRule("lookup", PolicyVerdict.ASK),))

        _, timeline = self._run(model, executor, policy=policy)

        self.assertEqual(executor.calls, [])
        self.assertEqual(timeline.first(PolicyTriggered).decision, "ask")
        message = model.requests[-1][-1]["content"]
        self.assertIn("需要人工确认", message)

    def test_blocked_message_does_not_leak_arguments(self) -> None:
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
        )
        policy = PolicyEngine(rules=(AllowlistRule(frozenset({"other"})),))

        _, timeline = self._run(model, RecorderExecutor(), policy=policy)

        blocked = timeline.first(GuardrailBlocked)
        self.assertNotIn("x", blocked.reason)
        self.assertNotIn("key", blocked.reason)

    def test_blocked_call_keeps_event_order(self) -> None:
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
        )
        policy = PolicyEngine(rules=(ToolNameRule("lookup", PolicyVerdict.DENY),))

        _, timeline = self._run(model, RecorderExecutor(), policy=policy)

        self.assertEqual(
            timeline.types()[5:9],
            [
                "run.tool.call_started",
                "run.policy.triggered",
                "run.policy.guardrail_blocked",
                "run.tool.call_ended",
            ],
        )


class ToolProgressEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(run_id="run-progress")

    def _run(
        self, executor: Any
    ) -> tuple[Any, RunTimeline]:
        timeline = RunTimeline()
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
        )
        runner = AgentRunner(model, StubRegistry(), executor, max_steps=4)
        return runner.run("问题", context=self.context, events=timeline), timeline

    def test_progress_reports_become_events(self) -> None:
        executor = ProgressExecutor(
            [
                ProgressReport(completed=1, total=3, message="第一步"),
                ProgressReport(completed=2, total=3, message="第二步"),
                ProgressReport(completed=3, total=3),
            ]
        )

        _, timeline = self._run(executor)

        progress = timeline.of_type(ToolProgress)
        self.assertEqual([event.completed for event in progress], [1, 2, 3])
        self.assertEqual(progress[0].total, 3)
        self.assertEqual(progress[0].message, "第一步")
        self.assertEqual(progress[0].call_id, "call-1")
        self.assertEqual(progress[0].name, "lookup")
        self.assertTrue(executor.received_callback)
        self.assertEqual(timeline.first(ToolCallEnd).is_error, False)

    def test_executor_without_progress_reports_no_events(self) -> None:
        _, timeline = self._run(ProgressExecutor())

        self.assertEqual(timeline.of_type(ToolProgress), ())
        self.assertEqual(timeline.first(RunCompleted).steps, 2)

    def test_progress_callback_is_none_without_a_sink(self) -> None:
        executor = ProgressExecutor()
        runner = AgentRunner(
            ScriptedModel(
                [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
            ),
            StubRegistry(),
            executor,
            max_steps=4,
        )

        runner.run("问题", context=self.context)

        self.assertFalse(executor.received_callback)

    def test_progress_after_the_call_ends_is_ignored(self) -> None:
        """执行器延迟上报不应产生脱离调用时序的事件。"""
        executor = ProgressExecutor()
        timeline = RunTimeline()
        model = ScriptedModel(
            [ModelResult(tool_calls=[tool_call()]), ModelResult(text="完成")]
        )
        runner = AgentRunner(model, StubRegistry(), executor, max_steps=4)
        leaked: list[ProgressCallback] = []

        def capture(
            call: ToolCall,
            context: ToolContext,
            on_progress: ProgressCallback | None = None,
        ) -> ToolResult:
            if on_progress is not None:
                leaked.append(on_progress)
            return ToolResult(output={"value": 42})

        executor.execute = capture  # type: ignore[method-assign]
        runner.run("问题", context=self.context, events=timeline)
        leaked[0](ProgressReport(completed=9))

        self.assertEqual(timeline.of_type(ToolProgress), ())


class ContextCompressedEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(run_id="run-context")

    def test_compression_emits_event_with_counts(self) -> None:
        window = ContextWindow(token_budget=30)
        for index in range(6):
            window.add(
                {"role": MessageRole.USER.value, "content": f"历史消息 {index} " * 12}
            )
        timeline = RunTimeline()
        model = ScriptedModel([ModelResult(text="完成")])
        runner = AgentRunner(
            model, StubRegistry(), RecorderExecutor(), max_steps=4, context=window
        )

        runner.run("这次的问题", context=self.context, events=timeline)

        compressed = timeline.first(ContextCompressed)
        self.assertIsNotNone(compressed)
        self.assertGreater(compressed.messages_removed, 0)
        self.assertLess(compressed.tokens_after, compressed.tokens_before)
        self.assertEqual(compressed.strategy, "trim_oldest")

    def test_small_context_emits_no_compression_event(self) -> None:
        timeline = RunTimeline()
        model = ScriptedModel([ModelResult(text="完成")])
        runner = AgentRunner(
            model,
            StubRegistry(),
            RecorderExecutor(),
            max_steps=4,
            token_budget=10_000,
        )

        runner.run("简短问题", context=self.context, events=timeline)

        self.assertEqual(timeline.of_type(ContextCompressed), ())

    def test_runner_sends_prepared_messages_to_the_model(self) -> None:
        window = ContextWindow(token_budget=10_000, system_prompt="系统提示")
        timeline = RunTimeline()
        model = ScriptedModel([ModelResult(text="完成")])
        runner = AgentRunner(
            model, StubRegistry(), RecorderExecutor(), max_steps=4, context=window
        )

        runner.run("问题", context=self.context, events=timeline)

        sent = model.requests[0]
        self.assertEqual(sent[0]["role"], MessageRole.SYSTEM.value)
        self.assertEqual(sent[-1]["content"], "问题")


if __name__ == "__main__":
    unittest.main()
