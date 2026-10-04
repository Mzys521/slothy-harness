"""令牌估算契约（核心层）。

核心层不做真实分词：分词器属于具体提供方。运行器只需要一个保守的规模判断，
因此用可替换的估算器表达该能力，并提供与提供方无关的启发式实现。
"""

from collections.abc import Sequence
from json import dumps
from typing import Any, Protocol

#: 启发式估算使用的“每个令牌对应字符数”。中文等非 ASCII 文本每字符约占一个令牌，
#: 因此对非 ASCII 字符单独计数，估算结果偏保守。
ASCII_CHARACTERS_PER_TOKEN = 4


class TokenEstimator(Protocol):
    """估算消息规模的最小契约。"""

    def estimate(self, messages: Sequence[dict[str, Any]]) -> int:
        """返回一组消息的估算令牌数。"""
        ...


class HeuristicTokenEstimator:
    """不使用分词器的保守估算器。

    估算值只用于判断上下文是否需要裁剪，不用于计费或对外报告，因此不追求
    与提供方的精确一致。
    """

    def estimate(self, messages: Sequence[dict[str, Any]]) -> int:
        """按字符数估算令牌数，非 ASCII 字符单独计数。"""
        total = 0
        for message in messages:
            total += self.estimate_text(str(message.get("content") or ""))
            for call in message.get("tool_calls") or ():
                function = call.get("function") or call
                arguments = function.get("arguments", {})
                if not isinstance(arguments, str):
                    arguments = dumps(arguments, ensure_ascii=False, allow_nan=False)
                total += self.estimate_text(str(function.get("name") or ""))
                total += self.estimate_text(arguments)
                total += self.estimate_text(
                    str(call.get("call_id") or call.get("id") or "")
                )
                total += 4
            total += self.estimate_text(
                str(message.get("call_id") or message.get("tool_call_id") or "")
            )
            # 每条消息本身带有角色和分帧开销。
            total += 4
        return total

    @staticmethod
    def estimate_text(text: str) -> int:
        """估算一段文本的令牌数。"""
        ascii_characters = sum(1 for character in text if character.isascii())
        other_characters = len(text) - ascii_characters
        whole = ascii_characters // ASCII_CHARACTERS_PER_TOKEN
        remainder = 1 if ascii_characters % ASCII_CHARACTERS_PER_TOKEN else 0
        return whole + remainder + other_characters
