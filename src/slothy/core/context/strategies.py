"""窗口压缩策略：完整往返裁剪、工具结果缩短与可注入的历史摘要。"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from json import dumps, loads
from typing import Any

from .contracts import ContextBudgetExceededError, ContextError, Summarizer
from .estimator import TokenEstimator
from .window import CompressionRecord, WindowBuild


@dataclass
class _Trimmed:
    messages: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    truncated: int = 0


def _groups(messages: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """把助手调用和其全部工具结果作为一个不能拆开的单位。"""
    groups: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message["role"] == "tool":
            raise ContextError("工具结果缺少对应的助手调用")
        group = [message]
        index += 1
        calls = message.get("tool_calls") or []
        if calls:
            expected = [call.get("call_id") or call.get("id") for call in calls]
            if (
                any(not call_id for call_id in expected)
                or len(set(expected)) != len(expected)
            ):
                raise ContextError("助手工具调用必须具有无重复的调用标识")
            while index < len(messages) and messages[index]["role"] == "tool":
                group.append(messages[index])
                index += 1
            received = [item.get("call_id") for item in group[1:]]
            if sorted(received) != sorted(expected):
                raise ContextError("助手工具调用与结果未完整配对")
        groups.append(group)
    return groups


def _tool_preview(original: str, preview_length: int) -> str:
    """保持合法 JSON 和工具错误标记，同时明确告知模型结果已缩短。"""
    is_error = False
    try:
        decoded = loads(original)
        if isinstance(decoded, dict):
            is_error = decoded.get("is_error") is True
    except (ValueError, TypeError):
        pass
    return dumps(
        {
            "output": {
                "context_truncated": True,
                "original_characters": len(original),
                "preview": original[:preview_length],
            },
            "is_error": is_error,
        },
        ensure_ascii=False,
    )


def _trim(
    messages: Sequence[dict[str, Any]], token_budget: int, estimator: TokenEstimator
) -> _Trimmed:
    groups = _groups(deepcopy(messages))
    protected = {len(groups) - 1} if groups else set()
    # 最新用户意图和系统提示保持完整；中间的旧工具往返可以整组丢弃。
    for index in range(len(groups) - 1, -1, -1):
        if groups[index][0]["role"] == "user":
            protected.add(index)
            break
    protected.update(
        index for index, group in enumerate(groups) if group[0]["role"] == "system"
    )
    selected = set(range(len(groups)))

    def flatten() -> list[dict[str, Any]]:
        return [message for index in sorted(selected) for message in groups[index]]

    kept = flatten()
    removed: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if estimator.estimate(kept) <= token_budget:
            break
        if index in protected:
            continue
        selected.remove(index)
        removed.extend(group)
        kept = flatten()

    truncated = 0
    tools = sorted(
        (message for message in kept if message["role"] == "tool"),
        key=lambda message: len(message["content"]),
        reverse=True,
    )
    for message in tools:
        if estimator.estimate(kept) <= token_budget:
            break
        original = message["content"]
        previous_tokens = estimator.estimate(kept)
        message["content"] = _tool_preview(original, 0)
        if estimator.estimate(kept) >= previous_tokens:
            message["content"] = original
            continue
        # 找到完整请求能容纳的最大预览；最小标记也超限时先缩短本条，再处理下一条。
        low, high = 0, len(original)
        if estimator.estimate(kept) <= token_budget:
            while low < high:
                middle = (low + high + 1) // 2
                message["content"] = _tool_preview(original, middle)
                if estimator.estimate(kept) <= token_budget:
                    low = middle
                else:
                    high = middle - 1
        message["content"] = _tool_preview(original, low)
        truncated += 1

    if estimator.estimate(kept) > token_budget:
        raise ContextBudgetExceededError(
            "系统提示、最新用户消息或工具调用结构超过上下文预算"
        )
    return _Trimmed(kept, removed, truncated)


def _build(
    original: Sequence[dict[str, Any]],
    trimmed: _Trimmed,
    estimator: TokenEstimator,
    strategy: str,
) -> WindowBuild:
    record = None
    if trimmed.removed or trimmed.truncated:
        record = CompressionRecord(
            tokens_before=estimator.estimate(original),
            tokens_after=estimator.estimate(trimmed.messages),
            messages_removed=len(trimmed.removed),
            messages_truncated=trimmed.truncated,
            strategy=strategy,
            # 事件只描述计数，不包含历史、摘要或工具结果原文。
            preview=f"removed={len(trimmed.removed)}, truncated={trimmed.truncated}",
        )
    return WindowBuild(messages=trimmed.messages, compression=record)


class TrimOldestStrategy:
    """按最早完整单位裁剪，必要时缩短保留的工具结果，使窗口符合预算。"""

    def compress(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        token_budget: int,
        estimator: TokenEstimator,
    ) -> WindowBuild:
        return _build(
            messages, _trim(messages, token_budget, estimator), estimator, "trim_oldest"
        )


class SummaryStrategy:
    """摘要旧历史；摘要器异常、空输出或预算不足时回退到完整单位截断。"""

    def __init__(
        self,
        summarizer: Summarizer,
        *,
        max_summary_tokens: int = 1024,
        max_input_tokens: int = 8192,
    ) -> None:
        if not callable(summarizer):
            raise TypeError("summarizer 必须可调用")
        for value in (max_summary_tokens, max_input_tokens):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("摘要输入和输出的 Token 预算必须是正整数")
        self._summarizer = summarizer
        self._max_summary_tokens = max_summary_tokens
        self._max_input_tokens = max_input_tokens
        self._fallback = TrimOldestStrategy()

    def compress(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        token_budget: int,
        estimator: TokenEstimator,
    ) -> WindowBuild:
        fallback = self._fallback.compress(
            messages, token_budget=token_budget, estimator=estimator
        )
        if fallback.compression is None:
            return fallback
        reserve = min(self._max_summary_tokens, max(1, token_budget // 4))
        try:
            trimmed = _trim(messages, token_budget - reserve, estimator)
            if not trimmed.removed:
                return fallback
            source = _trim(trimmed.removed, self._max_input_tokens, estimator)
            text = self._summarizer(deepcopy(source.messages), reserve)
            if not isinstance(text, str) or not text.strip():
                return fallback
            summary = {
                "role": "assistant",
                "content": "",
                "context_summary": True,
            }
            # 摘要保持普通助手角色，不能提升成系统指令。
            position = 0
            while (
                position < len(trimmed.messages)
                and trimmed.messages[position]["role"] == "system"
            ):
                position += 1
            trimmed.messages.insert(position, summary)
            prefix = (
                "历史摘要（输入已截断，仅供上下文参考）：\n"
                if source.removed or source.truncated
                else "历史摘要（仅供上下文参考）：\n"
            )

            def summary_content(length: int) -> str:
                suffix = "\n[摘要已截断]" if length < len(text) else ""
                return prefix + text[:length] + suffix

            low, high = 0, len(text)
            summary["content"] = summary_content(0)
            if estimator.estimate([summary]) > reserve:
                return fallback
            while low < high:
                middle = (low + high + 1) // 2
                summary["content"] = summary_content(middle)
                if (
                    estimator.estimate([summary]) <= reserve
                    and estimator.estimate(trimmed.messages) <= token_budget
                ):
                    low = middle
                else:
                    high = middle - 1
            if not low:
                return fallback
            summary["content"] = summary_content(low)
            if (
                estimator.estimate([summary]) > reserve
                or estimator.estimate(trimmed.messages) > token_budget
            ):
                return fallback
            return _build(messages, trimmed, estimator, "summarize")
        except Exception:
            # 摘要是附加压缩能力，其失败不应阻断仍可安全截断的主任务。
            return fallback
