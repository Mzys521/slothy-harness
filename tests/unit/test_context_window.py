"""上下文窗口、令牌估算与裁剪的测试。"""

import unittest

from slothy.core.context import (
    ContextWindow,
    HeuristicTokenEstimator,
    MessageRole,
)

SYSTEM_PROMPT = "你是一个简洁的助手。"


def user(text: str) -> dict[str, str]:
    return {"role": MessageRole.USER.value, "content": text}


def assistant(text: str = "") -> dict[str, str]:
    return {"role": MessageRole.ASSISTANT.value, "content": text}


def tool_result(call_id: str, text: str = "结果") -> dict[str, str]:
    return {"role": MessageRole.TOOL.value, "call_id": call_id, "content": text}


class HeuristicTokenEstimatorTests(unittest.TestCase):
    def test_estimates_ascii_and_non_ascii_separately(self) -> None:
        estimator = HeuristicTokenEstimator()

        self.assertEqual(estimator.estimate_text(""), 0)
        self.assertEqual(estimator.estimate_text("abcd"), 1)
        self.assertEqual(estimator.estimate_text("abcde"), 2)
        self.assertEqual(estimator.estimate_text("中文"), 2)

    def test_estimate_counts_messages_and_tool_calls(self) -> None:
        estimator = HeuristicTokenEstimator()
        message = {
            "role": MessageRole.ASSISTANT.value,
            "content": "回答内容",
            "tool_calls": [
                {"call_id": "c", "name": "lookup", "arguments": {"key": "x"}}
            ],
        }

        self.assertGreater(estimator.estimate([message]), 4)
        self.assertEqual(estimator.estimate([]), 0)


class ContextWindowTests(unittest.TestCase):
    def test_rejects_invalid_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "token_budget"):
            ContextWindow(token_budget=0)

    def test_build_without_compression_returns_all_messages(self) -> None:
        window = ContextWindow(token_budget=10_000, system_prompt=SYSTEM_PROMPT)
        window.add(user("你好"))

        build = window.build()

        self.assertIsNone(build.compression)
        self.assertIsNone(window.last_compression)
        self.assertEqual(
            [message["role"] for message in build.messages],
            [MessageRole.SYSTEM.value, MessageRole.USER.value],
        )

    def test_compression_trims_oldest_and_keeps_system_prompt(self) -> None:
        window = ContextWindow(token_budget=40, system_prompt=SYSTEM_PROMPT)
        for index in range(6):
            window.add(user(f"第 {index} 条比较长的历史消息" * 2))

        build = window.build()

        self.assertIsNotNone(build.compression)
        record = build.compression
        self.assertEqual(record.strategy, "trim_oldest")
        self.assertGreater(record.messages_removed, 0)
        self.assertLess(record.tokens_after, record.tokens_before)
        self.assertLessEqual(record.tokens_after, window.token_budget)
        self.assertEqual(build.messages[0]["role"], MessageRole.SYSTEM.value)
        self.assertEqual(build.messages[0]["content"], SYSTEM_PROMPT)

    def test_compression_keeps_tool_call_pairing(self) -> None:
        """尾部工具结果必须与其助手消息一起保留，否则请求结构不合法。"""
        window = ContextWindow(token_budget=30)
        window.add(user("问题" * 40))
        window.add(assistant())
        window.add(tool_result("call-1", "很长的工具结果" * 20))

        build = window.build()

        roles = [message["role"] for message in build.messages]
        self.assertIn(MessageRole.TOOL.value, roles)
        self.assertEqual(roles[-2:], [MessageRole.ASSISTANT.value, MessageRole.TOOL.value])

    def test_preview_is_truncated_and_excludes_tool_content(self) -> None:
        window = ContextWindow(token_budget=20)
        window.add(user("被裁剪的用户消息 " * 20))
        window.add(user("仍然保留的最新消息 " * 5))

        record = window.build().compression

        self.assertIsNotNone(record)
        self.assertLessEqual(len(record.preview), 120)
        self.assertNotIn("结果", record.preview)

    def test_window_state_shrinks_after_compression(self) -> None:
        window = ContextWindow(token_budget=30)
        for index in range(6):
            window.add(user(f"消息 {index} " * 12))

        before = len(window.messages)
        window.build()

        self.assertLess(len(window.messages), before)

    def test_second_build_without_growth_reports_no_new_compression(self) -> None:
        window = ContextWindow(token_budget=30)
        for index in range(6):
            window.add(user(f"消息 {index} " * 12))

        first = window.build()
        second = window.build()

        self.assertIsNotNone(first.compression)
        self.assertIsNone(second.compression)

    def test_latest_message_is_always_kept_even_over_budget(self) -> None:
        """只剩一条超长消息时仍保留它，避免请求失去最新上下文。"""
        window = ContextWindow(token_budget=5)
        window.add(user("很久以前" * 40))
        window.add(user("最新问题" * 40))

        build = window.build()

        self.assertEqual(len(build.messages), 1)
        self.assertEqual(build.messages[0]["content"], "最新问题" * 40)
        self.assertIsNotNone(build.compression)


if __name__ == "__main__":
    unittest.main()
