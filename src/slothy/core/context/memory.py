"""内存 Context：隔离原始历史、发送窗口和可替换的压缩策略。"""

from __future__ import annotations

from copy import deepcopy
from json import dumps
from typing import Any

from .contracts import (
    CompressionStrategy,
    ContextBudgetExceededError,
    ContextError,
)
from .estimator import HeuristicTokenEstimator, TokenEstimator
from .messages import MessageRole
from .strategies import TrimOldestStrategy, _groups
from .window import DEFAULT_TOKEN_BUDGET, CompressionRecord, WindowBuild


class InMemoryContext:
    """保存完整历史，模型每次只接收预算内的窗口副本。

    默认每次 Run 创建一个实例；显式共享实例可以保留历史，但不应并发写入。
    token_budget 是注入计数器度量下的硬上限；默认计数器仍是启发式估算。
    """

    def __init__(
        self,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        estimator: TokenEstimator | None = None,
        strategy: CompressionStrategy | None = None,
        system_prompt: str | None = None,
    ) -> None:
        if (
            isinstance(token_budget, bool)
            or not isinstance(token_budget, int)
            or token_budget < 1
        ):
            raise ValueError("token_budget 必须是正整数")
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise TypeError("system_prompt 必须是字符串")
        self.token_budget = token_budget
        self.estimator = (
            estimator if estimator is not None else HeuristicTokenEstimator()
        )
        self.strategy = strategy if strategy is not None else TrimOldestStrategy()
        self._system_prompt = system_prompt
        self._history: list[dict[str, Any]] = []
        self._active: list[dict[str, Any]] = []
        self._last_compression: CompressionRecord | None = None

    def add(self, message: dict[str, Any]) -> None:
        prepared = self._validate_message(message)
        self._history.append(deepcopy(prepared))
        self._active.append(prepared)

    def get_history(self) -> list[dict[str, Any]]:
        """返回原始历史副本，压缩和模型对副本的修改都不会污染历史。"""
        return deepcopy([*self._system_messages(), *self._history])

    def snapshot_state(self) -> dict[str, Any]:
        return deepcopy({
            "kind": "in_memory", "token_budget": self.token_budget,
            "system_prompt": self._system_prompt,
            "history": self._history, "active": self._active,
        })

    def restore_state(self, data: dict[str, Any]) -> None:
        if (
            not isinstance(data, dict) or set(data) != {
                "kind", "token_budget", "system_prompt", "history", "active",
            }
            or data["kind"] != "in_memory"
            or data["token_budget"] != self.token_budget
            or data["system_prompt"] != self._system_prompt
            or not isinstance(data["history"], list)
            or not isinstance(data["active"], list)
        ):
            raise ContextError("上下文快照配置不匹配")
        history = [self._validate_message(item) for item in data["history"]]
        active = [self._validate_message(item) for item in data["active"]]
        self._history, self._active = history, active
        self._last_compression = None

    def count_tokens(self) -> int:
        """返回当前活动上下文的规模；不会触发摘要或裁剪。"""
        return self._count([*self._system_messages(), *self._active])

    def get_windowed_messages(self) -> list[dict[str, Any]]:
        original = deepcopy([*self._system_messages(), *self._active])
        # 在调用策略前也检查计数器输出，避免无效预算比较。
        self._count(original)
        result = self.strategy.compress(
            deepcopy(original), token_budget=self.token_budget, estimator=self.estimator
        )
        if not isinstance(result, WindowBuild):
            raise ContextError("压缩策略必须返回 WindowBuild")
        messages = [self._validate_message(message) for message in result.messages]
        if self._count(messages) > self.token_budget:
            raise ContextBudgetExceededError("压缩策略返回的窗口仍超过上下文预算")
        if [m for m in messages if m["role"] == "system"] != [
            m for m in original if m["role"] == "system"
        ]:
            raise ContextError("压缩策略不能修改或移除系统提示")
        # 所有策略都必须保持最新用户意图，并返回完整的工具往返。
        latest_user = next(
            (m for m in reversed(original) if m["role"] == "user"), None
        )
        if latest_user is not None and latest_user not in messages:
            raise ContextError("压缩策略不能修改或移除最新用户消息")
        _groups(messages)
        original_groups = _groups(original)
        if original_groups:
            for latest in original_groups[-1]:
                if latest["role"] != "tool":
                    if latest not in messages:
                        raise ContextError("压缩策略不能移除最新消息或工具调用")
                elif not any(
                    {key: value for key, value in candidate.items() if key != "content"}
                    == {key: value for key, value in latest.items() if key != "content"}
                    for candidate in messages
                ):
                    raise ContextError("压缩策略不能移除最新工具结果的调用结构")
        # 策略只能修改工作副本；成功后才提交新的活动窗口。
        if self._system_prompt is not None:
            if not messages or messages[0] != self._system_messages()[0]:
                raise ContextError("系统提示必须保持在窗口开头")
            messages = messages[1:]
        self._active = deepcopy(messages)
        self._last_compression = result.compression
        return deepcopy([*self._system_messages(), *messages])

    @property
    def last_compression(self) -> CompressionRecord | None:
        return self._last_compression

    def _system_messages(self) -> list[dict[str, Any]]:
        if self._system_prompt is None:
            return []
        return [{"role": "system", "content": self._system_prompt}]

    def _count(self, messages: list[dict[str, Any]]) -> int:
        count = self.estimator.estimate(messages)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContextError("Token 计数器必须返回非负整数")
        return count

    @staticmethod
    def _validate_message(message: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(message, dict):
            raise TypeError("上下文消息必须是字典")
        if not isinstance(message.get("role"), str) or message["role"] not in {
            role.value for role in MessageRole
        }:
            raise ContextError("不支持的上下文消息角色")
        if not isinstance(message.get("content", ""), str):
            raise ContextError("上下文消息内容必须是字符串")
        if message["role"] == "tool" and (
            not isinstance(message.get("call_id"), str) or not message["call_id"]
        ):
            raise ContextError("工具结果必须携带调用标识")
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or (calls and message["role"] != "assistant"):
            raise ContextError("tool_calls 必须是助手消息中的列表")
        for call in calls:
            if not isinstance(call, dict):
                raise ContextError("工具调用必须是字典")
            call_id = call.get("call_id") or call.get("id")
            if not isinstance(call_id, str) or not call_id:
                raise ContextError("工具调用必须携带调用标识")
        try:
            dumps(message, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ContextError("上下文消息必须能编码为 JSON") from error
        prepared = deepcopy(message)
        prepared.setdefault("content", "")
        return prepared
