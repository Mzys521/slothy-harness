"""长任务在默认 8k 预算内持续往返，切换 Context/策略无需修改 Runner。"""

import json
import unittest
from copy import deepcopy

from slothy.core.context import (
    ContextBudgetExceededError,
    HeuristicTokenEstimator,
    InMemoryContext,
    SummaryStrategy,
)
from slothy.core.events import (
    ContextCompressed, ModelRequestStart, RunFailed, RunTimeline
)
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.runtime import AgentRunner, Run, RunCancelledError, RunStatus
from slothy.core.tools import ToolContext, ToolResult


class Registry:
    def definitions(self):
        return [{"name": "lookup", "description": "读取下一批数据"}]


class LongTaskModel(ModelProvider):
    def __init__(self, rounds=16):
        self.rounds = rounds
        self.requests = []
        self.estimator = HeuristicTokenEstimator()

    def generate(self, messages, **kwargs):
        if self.estimator.estimate(messages) > 8192:
            raise AssertionError("模型收到超过 8k 预算的请求")
        pending = set()
        for message in messages:
            calls = message.get("tool_calls") or []
            if calls:
                if pending:
                    raise AssertionError("前一个工具往返不完整")
                pending = {call["call_id"] for call in calls}
            if message["role"] == "tool":
                pending.remove(message["call_id"])
                json.loads(message["content"])
        if pending:
            raise AssertionError("工具结果与助手调用未配对")
        self.requests.append(deepcopy(messages))
        if len(self.requests) <= self.rounds:
            return ModelResult(tool_calls=[
                ToolCall(f"call-{len(self.requests)}", "lookup", {})
            ])
        return ModelResult(text="长任务完成")


class LargeResultExecutor:
    def execute(self, call, context, on_progress=None):
        size = 12000 if call.call_id == "call-1" else 700
        return ToolResult(output={"data": "工具数据" * size, "call": call.call_id})


class ContextIntegrationTests(unittest.TestCase):
    def test_long_task_trims_at_8k_and_keeps_full_history(self):
        context = InMemoryContext(system_prompt="系统提示")
        model = LongTaskModel()
        timeline = RunTimeline()

        result = AgentRunner(
            model, Registry(), LargeResultExecutor(), context=context, max_steps=17
        ).run("分析全部数据", context=ToolContext("long-trim"), events=timeline)

        self.assertEqual((result.output, result.steps), ("长任务完成", 17))
        self.assertGreater(context.estimator.estimate(context.get_history()), 8192)
        self.assertEqual(
            context.get_history()[-1], {"role": "assistant", "content": "长任务完成"}
        )
        compressed = timeline.of_type(ContextCompressed)
        self.assertTrue(any(event.messages_removed for event in compressed))
        self.assertTrue(any(event.messages_truncated for event in compressed))
        self.assertTrue(all(event.tokens_after <= 8192 for event in compressed))
        self.assertTrue(all(
            user_message_present(request) for request in model.requests
        ))
        self.assertEqual(
            [event.sequence for event in timeline.events],
            list(range(1, len(timeline.events) + 1)),
        )

    def test_same_runner_handles_summary_success_and_failure(self):
        calls = []

        def summarizer(messages, token_budget):
            calls.append(messages)
            return "先前步骤已完成，继续读取下一批数据。"

        def unavailable(messages, token_budget):
            raise RuntimeError("摘要器不可用")

        for summarize in (summarizer, unavailable):
            with self.subTest(summarize=summarize):
                context = InMemoryContext(strategy=SummaryStrategy(summarize))
                model = LongTaskModel()
                timeline = RunTimeline()
                result = AgentRunner(
                    model, Registry(), LargeResultExecutor(),
                    context=context, max_steps=17,
                ).run(
                    "分析全部数据", context=ToolContext("long-summary"), events=timeline
                )
                self.assertEqual(result.run.status, RunStatus.COMPLETED)
                self.assertGreater(
                    context.estimator.estimate(context.get_history()), 8192
                )
                if summarize is summarizer:
                    self.assertTrue(calls)
                    self.assertTrue(any(
                        m.get("context_summary") for req in model.requests for m in req
                    ))
                    self.assertTrue(any(
                        e.strategy == "summarize"
                        for e in timeline.of_type(ContextCompressed)
                    ))
                else:
                    self.assertTrue(all(
                        e.strategy == "trim_oldest"
                        for e in timeline.of_type(ContextCompressed)
                    ))

    def test_injected_context_needs_no_public_message_list(self):
        class IndependentContext:
            last_compression = None

            def __init__(self):
                self.received = []
                self.window_requests = 0

            def add(self, message):
                self.received.append(deepcopy(message))

            def get_windowed_messages(self):
                self.window_requests += 1
                return deepcopy(self.received)

        context = IndependentContext()
        model = LongTaskModel(rounds=1)

        class SmallResultExecutor:
            def execute(self, call, context, on_progress=None):
                return ToolResult(output="结果")

        runner = AgentRunner(model, Registry(), SmallResultExecutor(), context=context)
        result = runner.run(
            "独立上下文", context=ToolContext("custom-context")
        )

        self.assertEqual(result.steps, 2)
        self.assertEqual(context.window_requests, 2)
        self.assertEqual(context.received[-1]["content"], "长任务完成")

    def test_cancellation_during_summary_stops_before_model_call(self):
        runtime = Run("cancel-summary", max_steps=8)

        def cancelling(messages, token_budget):
            runtime.cancel()
            return "历史摘要。"

        context = InMemoryContext(strategy=SummaryStrategy(cancelling))
        for index in range(4):
            context.add({"role": "user", "content": f"旧历史 {index} " * 700})
        model = LongTaskModel(rounds=0)
        timeline = RunTimeline()

        with self.assertRaises(RunCancelledError):
            AgentRunner(model, Registry(), LargeResultExecutor(), context=context).run(
                "新的目标", context=ToolContext(runtime.run_id),
                runtime=runtime, events=timeline,
            )

        self.assertEqual(model.requests, [])
        self.assertEqual(timeline.of_type(ModelRequestStart), ())
        self.assertEqual(runtime.status, RunStatus.CANCELLED)

    def test_impossible_budget_fails_run_before_model_with_safe_classification(self):
        context = InMemoryContext(token_budget=30, system_prompt="系统提示" * 100)
        model = LongTaskModel(rounds=0)
        runtime = Run("context-budget-error", max_steps=8)
        timeline = RunTimeline()

        with self.assertRaises(ContextBudgetExceededError):
            AgentRunner(model, Registry(), LargeResultExecutor(), context=context).run(
                "新的目标", context=ToolContext(runtime.run_id),
                runtime=runtime, events=timeline,
            )

        self.assertEqual(model.requests, [])
        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(
            timeline.first(RunFailed).error.error_code, "context_budget_exceeded"
        )


def user_message_present(messages):
    return any(m["role"] == "user" and m["content"] == "分析全部数据" for m in messages)


if __name__ == "__main__":
    unittest.main()
