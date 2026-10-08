"""公开压缩策略的兼容入口；实现委托给共享缩减器。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .contracts import Summarizer
from .estimator import TokenEstimator
from .records import WindowBuild
from .reduction import WindowReducer


class TrimOldestStrategy:
    def compress(self, messages: Sequence[dict[str, Any]], *, token_budget: int,
                 estimator: TokenEstimator) -> WindowBuild:
        return WindowReducer(estimator, token_budget).reduce(messages)


class SummaryStrategy:
    def __init__(self, summarizer: Summarizer, *, max_summary_tokens: int = 1024,
                 max_input_tokens: int = 8192) -> None:
        if not callable(summarizer):
            raise TypeError("summarizer 必须可调用")
        for name, value in (("max_summary_tokens", max_summary_tokens), ("max_input_tokens", max_input_tokens)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} 必须是正整数")
        self._summarizer = summarizer
        self._max_summary_tokens, self._max_input_tokens = max_summary_tokens, max_input_tokens

    def compress(self, messages: Sequence[dict[str, Any]], *, token_budget: int,
                 estimator: TokenEstimator) -> WindowBuild:
        return WindowReducer(estimator, token_budget).reduce(
            messages, summarizer=self._summarizer, summary_tokens=self._max_summary_tokens,
            summary_input_tokens=self._max_input_tokens)
