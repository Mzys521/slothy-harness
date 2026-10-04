"""正式 Context 的历史隔离、硬预算、工具配对与摘要回退测试。"""

import json
import unittest

from slothy.core.context import (
    Context,
    ContextBudgetExceededError,
    ContextError,
    HeuristicTokenEstimator,
    InMemoryContext,
    SummaryStrategy,
    WindowBuild,
)
from slothy.core.events import describe_error


def user(text):
    return {"role": "user", "content": text}


def exchange(context, call_id, text, *, is_error=False):
    context.add({
        "role": "assistant", "content": "",
        "tool_calls": [{"call_id": call_id, "name": "lookup", "arguments": {}}],
    })
    context.add({
        "role": "tool", "call_id": call_id,
        "content": json.dumps(
            {"output": text, "is_error": is_error}, ensure_ascii=False
        ),
    })


class ContextSystemTests(unittest.TestCase):
    def test_default_context_implements_protocol_without_exposing_messages(self):
        context = InMemoryContext()

        self.assertIsInstance(context, Context)
        self.assertEqual(context.token_budget, 8192)
        self.assertFalse(hasattr(context, "messages"))
        self.assertEqual(context.get_history(), [])

    def test_input_history_and_window_snapshots_are_isolated(self):
        context = InMemoryContext()
        original = user("原始用户输入")
        context.add(original)
        original["content"] = "调用方改写"
        history = context.get_history()
        history[0]["content"] = "历史副本改写"
        window = context.get_windowed_messages()
        window[0]["content"] = "模型改写"

        self.assertEqual(context.get_history(), [user("原始用户输入")])
        self.assertEqual(context.get_windowed_messages(), [user("原始用户输入")])

    def test_neutral_and_provider_tool_arguments_are_counted(self):
        estimator = HeuristicTokenEstimator()
        arguments = {"query": "大参数" * 3000}
        neutral = [{"role": "assistant", "tool_calls": [{
            "call_id": "c", "name": "lookup", "arguments": arguments,
        }]}]
        provider = [{"role": "assistant", "tool_calls": [{
            "id": "c", "function": {"name": "lookup", "arguments": arguments},
        }]}]

        self.assertGreater(estimator.estimate(neutral), 8192)
        self.assertEqual(estimator.estimate(neutral), estimator.estimate(provider))

    def test_old_exchanges_are_removed_as_complete_units(self):
        context = InMemoryContext(token_budget=180, system_prompt="系统提示")
        context.add(user("当前目标"))
        exchange(context, "old-1", "历史结果" * 100)
        exchange(context, "old-2", "历史结果" * 100)
        exchange(context, "latest", "最新结果")
        full_history = context.get_history()

        window = context.get_windowed_messages()

        self.assertEqual(window[:2], [
            {"role": "system", "content": "系统提示"}, user("当前目标")
        ])
        self.assertEqual(
            [m.get("call_id") for m in window if m["role"] == "tool"], ["latest"]
        )
        self.assertEqual(window[-2]["tool_calls"][0]["call_id"], "latest")
        self.assertEqual(context.last_compression.messages_removed, 4)
        self.assertEqual(context.get_history(), full_history)
        self.assertLessEqual(context.count_tokens(), 180)
        self.assertNotIn("历史结果", context.last_compression.preview)

    def test_oversized_tool_result_fits_with_system_and_error_flag_intact(self):
        context = InMemoryContext(system_prompt="系统提示")
        context.add(user("当前目标"))
        exchange(context, "latest", "大工具结果" * 10000, is_error=True)
        full_history = context.get_history()
        self.assertGreater(context.count_tokens(), 8192)

        window = context.get_windowed_messages()

        self.assertLessEqual(context.estimator.estimate(window), 8192)
        self.assertEqual(
            [m["role"] for m in window], ["system", "user", "assistant", "tool"]
        )
        output = json.loads(window[-1]["content"])
        self.assertTrue(output["output"]["context_truncated"])
        self.assertTrue(output["is_error"])
        self.assertEqual(window[-1]["call_id"], "latest")
        self.assertEqual(context.last_compression.messages_truncated, 1)
        self.assertEqual(context.get_history(), full_history)
        context.get_windowed_messages()
        self.assertIsNone(context.last_compression)

    def test_multiple_latest_results_are_shortened_without_losing_pairing(self):
        context = InMemoryContext(token_budget=350)
        context.add(user("当前目标"))
        context.add({"role": "assistant", "content": "", "tool_calls": [
            {"call_id": call_id, "name": "lookup", "arguments": {}}
            for call_id in ("a", "b")
        ]})
        for call_id in ("a", "b"):
            context.add({"role": "tool", "call_id": call_id, "content": "数据" * 2000})

        window = context.get_windowed_messages()

        self.assertLessEqual(context.estimator.estimate(window), 350)
        self.assertEqual(
            [m["call_id"] for m in window if m["role"] == "tool"], ["a", "b"]
        )
        self.assertEqual(context.last_compression.messages_truncated, 2)

    def test_immutable_messages_over_budget_raise_a_classified_error(self):
        context = InMemoryContext(token_budget=30, system_prompt="超长系统提示" * 50)
        context.add(user("目标"))

        with self.assertRaises(ContextBudgetExceededError) as raised:
            context.get_windowed_messages()

        self.assertEqual(
            describe_error(raised.exception).error_code, "context_budget_exceeded"
        )
        self.assertEqual(context.get_history()[-1], user("目标"))

    def test_latest_user_and_tool_arguments_are_never_silently_changed(self):
        context = InMemoryContext(token_budget=100)
        context.add(user("用户输入" * 100))
        with self.assertRaises(ContextBudgetExceededError):
            context.get_windowed_messages()

        context = InMemoryContext(token_budget=100)
        context.add(user("目标"))
        context.add({"role": "assistant", "content": "", "tool_calls": [{
            "call_id": "c", "name": "lookup", "arguments": {"query": "参数" * 1000}
        }]})
        context.add({"role": "tool", "call_id": "c", "content": "结果"})
        with self.assertRaises(ContextBudgetExceededError):
            context.get_windowed_messages()

    def test_incomplete_exchange_is_rejected_before_model_request(self):
        context = InMemoryContext()
        context.add({"role": "assistant", "content": "", "tool_calls": [{
            "call_id": "c", "name": "lookup", "arguments": {}
        }]})
        with self.assertRaisesRegex(ContextError, "配对"):
            context.get_windowed_messages()

    def test_invalid_messages_and_counter_outputs_are_rejected(self):
        for message in ({"role": "unknown"}, {"role": "tool", "content": "x"}):
            with self.subTest(message=message), self.assertRaises(ContextError):
                InMemoryContext().add(message)

        class InvalidCounter:
            def estimate(self, messages):
                return -1

        context = InMemoryContext(estimator=InvalidCounter())
        context.add(user("目标"))
        with self.assertRaisesRegex(ContextError, "非负整数"):
            context.get_windowed_messages()

    def test_custom_counter_controls_the_window_budget(self):
        class WordCounter:
            def estimate(self, messages):
                return sum(len(m["content"].split()) for m in messages)

        context = InMemoryContext(token_budget=4, estimator=WordCounter())
        context.add(user("old history with four words"))
        context.add(user("keep these three"))

        self.assertEqual(context.get_windowed_messages(), [user("keep these three")])
        self.assertEqual(context.count_tokens(), 3)

    def test_strategy_cannot_mutate_protected_input_or_exceed_budget(self):
        class MutatingStrategy:
            def compress(self, messages, **kwargs):
                messages[0]["content"] = "改写系统提示"
                return WindowBuild(messages=messages)

        context = InMemoryContext(strategy=MutatingStrategy(), system_prompt="系统提示")
        context.add(user("目标"))
        before = context.get_history()
        with self.assertRaisesRegex(ContextError, "系统提示"):
            context.get_windowed_messages()
        self.assertEqual(context.get_history(), before)

        class UnboundedStrategy:
            def compress(self, messages, **kwargs):
                return WindowBuild(messages=messages)

        context = InMemoryContext(token_budget=10, strategy=UnboundedStrategy())
        context.add(user("用户输入" * 100))
        with self.assertRaises(ContextBudgetExceededError):
            context.get_windowed_messages()


class SummaryStrategyTests(unittest.TestCase):
    def _context(self, summarizer, *, max_summary_tokens=128):
        context = InMemoryContext(
            token_budget=700, system_prompt="系统提示",
            strategy=SummaryStrategy(summarizer, max_summary_tokens=max_summary_tokens),
        )
        context.add(user("当前目标"))
        exchange(context, "old", "重要历史结果" * 300)
        exchange(context, "latest", "最新结果")
        return context

    def test_injected_summarizer_receives_complete_old_exchange_and_budget(self):
        received = []

        def summarizer(messages, token_budget):
            received.append((messages, token_budget))
            return "重要历史结论：已确认数据有效。"

        context = self._context(summarizer)
        before = context.get_history()
        window = context.get_windowed_messages()

        self.assertEqual(len(received), 1)
        self.assertEqual([m["role"] for m in received[0][0]], ["assistant", "tool"])
        self.assertEqual(received[0][1], 128)
        summary = next(m for m in window if m.get("context_summary"))
        self.assertEqual(summary["role"], "assistant")
        self.assertIn("已确认数据有效", summary["content"])
        self.assertEqual(context.last_compression.strategy, "summarize")
        self.assertLessEqual(context.estimator.estimate(window), 700)
        self.assertEqual(context.get_history(), before)
        context.get_windowed_messages()
        self.assertIsNone(context.last_compression)
        self.assertEqual(len(received), 1)

    def test_too_long_summary_is_shortened_with_an_explicit_marker(self):
        context = self._context(lambda messages, budget: "summary " * 5000)

        window = context.get_windowed_messages()

        summary = next(m for m in window if m.get("context_summary"))
        self.assertIn("摘要已截断", summary["content"])
        self.assertLessEqual(context.estimator.estimate([summary]), 128)
        self.assertLessEqual(context.estimator.estimate(window), 700)

    def test_summarizer_exception_empty_or_invalid_output_falls_back_to_trim(self):
        def failed(messages, budget):
            raise RuntimeError("摘要服务故障")

        for summarizer in (
            failed, lambda messages, budget: "", lambda messages, budget: None
        ):
            with self.subTest(summarizer=summarizer):
                context = self._context(summarizer)
                window = context.get_windowed_messages()
                self.assertFalse(any(m.get("context_summary") for m in window))
                self.assertEqual(context.last_compression.strategy, "trim_oldest")
                self.assertLessEqual(context.estimator.estimate(window), 700)

    def test_summarizer_is_not_called_when_no_compression_is_needed(self):
        def unexpected(messages, budget):
            self.fail("不需要压缩时不能调用摘要器")

        context = InMemoryContext(strategy=SummaryStrategy(unexpected))
        context.add(user("简短问题"))

        self.assertEqual(context.get_windowed_messages(), [user("简短问题")])

    def test_summarizer_cannot_mutate_original_history(self):
        def mutating(messages, budget):
            messages[0]["tool_calls"][0]["arguments"]["injected"] = True
            return "已完成历史步骤。"

        context = self._context(mutating)
        before = context.get_history()
        context.get_windowed_messages()

        self.assertEqual(context.get_history(), before)

    def test_summary_input_is_bounded_even_when_retained_history_is_large(self):
        received = []

        def summarizer(messages, token_budget):
            received.append(messages)
            return "部分历史的重要结论。"

        context = InMemoryContext(
            token_budget=700,
            strategy=SummaryStrategy(summarizer, max_input_tokens=200),
        )
        for index in range(10):
            context.add(user(f"旧消息 {index} " * 20))
        context.add(user("最新目标"))
        context.get_windowed_messages()

        self.assertTrue(received)
        self.assertTrue(all(
            context.estimator.estimate(messages) <= 200 for messages in received
        ))


if __name__ == "__main__":
    unittest.main()
