"""InMemoryContext 公开兼容适配层；分层生产入口见 LayeredContext。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .config import DEFAULT_TOKEN_BUDGET
from .contracts import CompressionStrategy, ContextError
from .estimator import HeuristicTokenEstimator, TokenEstimator
from .records import CompressionRecord
from .reduction import MessageLedger
from .strategies import TrimOldestStrategy
from .validation import count_tokens, validate_message


class InMemoryContext:
    def __init__(self, *, token_budget: int = DEFAULT_TOKEN_BUDGET,
                 estimator: TokenEstimator | None = None,
                 strategy: CompressionStrategy | None = None,
                 system_prompt: str | None = None) -> None:
        if type(token_budget) is not int or token_budget < 1:
            raise ValueError("token_budget 必须是正整数")
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise TypeError("system_prompt 必须是字符串")
        self.token_budget = token_budget
        self.estimator = estimator if estimator is not None else HeuristicTokenEstimator()
        self.strategy = strategy if strategy is not None else TrimOldestStrategy()
        self._ledger = MessageLedger(token_budget, self.estimator, self.strategy, system_prompt)

    def add(self, message: dict[str, Any]) -> None:
        self._ledger.append(validate_message(message))

    def get_history(self) -> list[dict[str, Any]]:
        return deepcopy(self._ledger.systems() + self._ledger.history)

    def get_windowed_messages(self) -> list[dict[str, Any]]:
        self._ledger.token_budget, self._ledger.estimator, self._ledger.strategy = self.token_budget, self.estimator, self.strategy
        return self._ledger.window()

    def count_tokens(self) -> int:
        return count_tokens(self.estimator, self._ledger.systems() + self._ledger.active)

    @property
    def last_compression(self) -> CompressionRecord | None:
        return self._ledger.last_compression

    def snapshot_state(self) -> dict[str, Any]:
        return deepcopy({"kind": "in_memory", "token_budget": self.token_budget,
                         "system_prompt": self._ledger.system_prompt,
                         "history": self._ledger.history, "active": self._ledger.active})

    def restore_state(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or set(data) != {"kind", "token_budget", "system_prompt", "history", "active"} or data["kind"] != "in_memory" or data["token_budget"] != self.token_budget or data["system_prompt"] != self._ledger.system_prompt or not isinstance(data["history"], list) or not isinstance(data["active"], list):
            raise ContextError("上下文快照配置不匹配")
        history, active = ([validate_message(m) for m in data[key]] for key in ("history", "active"))
        self._ledger.history, self._ledger.active = history, active
        self._ledger.last_compression = None

    _validate_message = staticmethod(validate_message)
