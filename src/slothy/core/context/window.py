"""对话窗口：在令牌预算内维护消息，并在必要时裁剪最早的消息。

窗口只负责“哪些消息可以进入下一次模型请求”。它不调用模型、不做摘要，也不
读取提供方细节；裁剪结果通过 :class:`CompressionRecord` 描述，供上下文入口发出
``ContextCompressed`` 事件。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .estimator import HeuristicTokenEstimator, TokenEstimator
from .messages import MessageRole

#: 默认令牌预算。没有具体模型信息时使用，保证上下文不会无限增长。
DEFAULT_TOKEN_BUDGET = 8192

#: 预览的最大字符数，避免事件负载随被裁剪内容增长。
PREVIEW_LIMIT = 120


@dataclass(frozen=True)
class CompressionRecord:
    """一次上下文裁剪的结果，只含计数和安全预览。"""

    tokens_before: int
    tokens_after: int
    messages_removed: int
    strategy: str = "trim_oldest"
    #: 被移除内容的安全预览（仅文本、长度受限），供界面显示裁剪了什么。
    preview: str = ""
    #: 只缩短内容、仍保留角色及调用标识的工具结果数量。
    messages_truncated: int = 0


@dataclass(frozen=True)
class WindowBuild:
    """一次 ``ContextWindow.build`` 的结果。"""

    messages: list[dict[str, Any]]
    compression: CompressionRecord | None = None


@dataclass
class ContextWindow:
    """按令牌预算裁剪消息，并保留合法的“助手调用 + 工具结果”配对。

    系统提示单独保存，永不裁剪；裁剪从最早的非系统消息开始，并且不会切断最后
    一次模型响应的工具结果。至少保留最新的一条消息，即使它本身超出预算——丢弃
    它会让下一次请求失去最新上下文。估算只是保守判断，预算并非硬性上限。
    """

    token_budget: int = DEFAULT_TOKEN_BUDGET
    estimator: TokenEstimator = field(default_factory=HeuristicTokenEstimator)
    system_prompt: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    _last_compression: CompressionRecord | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """拒绝无法执行的预算配置。"""
        if self.token_budget < 1:
            raise ValueError("token_budget 必须至少为 1")

    def add(self, message: dict[str, Any]) -> None:
        """追加一条对话消息。"""
        self.messages.append(message)

    def snapshot_state(self) -> dict[str, Any]:
        from copy import deepcopy

        return deepcopy({
            "kind": "window", "token_budget": self.token_budget,
            "system_prompt": self.system_prompt, "messages": self.messages,
        })

    def restore_state(self, data: dict[str, Any]) -> None:
        from .memory import InMemoryContext
        from .contracts import ContextError

        if (
            set(data) != {"kind", "token_budget", "system_prompt", "messages"}
            or data["kind"] != "window" or data["token_budget"] != self.token_budget
            or data["system_prompt"] != self.system_prompt
            or not isinstance(data["messages"], list)
        ):
            raise ContextError("上下文快照配置不匹配")
        self.messages = [
            InMemoryContext._validate_message(item) for item in data["messages"]
        ]
        self._last_compression = None

    def get_windowed_messages(self) -> list[dict[str, Any]]:
        """兼容正式 Context 接口；保留本类既有的软预算行为。"""
        from copy import deepcopy

        return deepcopy(self.build().messages)

    def build(self) -> WindowBuild:
        """返回可交给模型的消息，必要时裁剪最早的消息。

        每次调用都会检查预算，因此返回的裁剪记录总是对应本次构建；没有实际裁掉
        任何消息时 ``compression`` 为 ``None``。
        """
        history = self._full_history()
        tokens_before = self.estimator.estimate(history)
        if tokens_before <= self.token_budget:
            self._last_compression = None
            return WindowBuild(messages=history)

        start = self._start_index()
        kept_from = self._trim_start(history)
        removed = history[start:kept_from]
        if not removed:
            self._last_compression = None
            return WindowBuild(messages=history)

        kept = [*self._system_message(), *history[kept_from:]]
        record = CompressionRecord(
            tokens_before=tokens_before,
            tokens_after=self.estimator.estimate(kept),
            messages_removed=len(removed),
            preview=self._preview(removed),
        )
        self.messages = history[kept_from:]
        self._last_compression = record
        return WindowBuild(messages=kept, compression=record)

    @property
    def last_compression(self) -> CompressionRecord | None:
        """返回最近一次裁剪记录；没有裁剪时为 ``None``。"""
        return self._last_compression

    def _full_history(self) -> list[dict[str, Any]]:
        """返回系统提示加全部对话消息，不修改窗口状态。"""
        system = self._system_message()
        return [*system, *self.messages]

    def _system_message(self) -> list[dict[str, Any]]:
        """返回系统提示消息；未设置时为空列表。"""
        if self.system_prompt is None:
            return []
        return [{"role": MessageRole.SYSTEM.value, "content": self.system_prompt}]

    def _start_index(self) -> int:
        """返回对话消息在完整历史中的起始下标。"""
        return 1 if self.system_prompt is not None else 0

    def _trim_start(self, history: Sequence[dict[str, Any]]) -> int:
        """返回裁剪后第一条保留的**对话**消息下标。

        从最早的消息开始逐条丢弃，直到估算规模进入预算。两条硬约束：

        - 不切断工具调用配对：尾部工具结果连同其助手消息一起保留。
        - 至少保留最新的一条消息。只剩对话消息且它超出预算时保留该条；存在系统
          提示时退到“只留系统提示”，此时返回值等于 ``_start_index()``。

        若连最小尾部都超出预算，就保留它——丢弃它会让请求失去最新上下文。估算
        只是保守判断，预算并非硬性上限。
        """
        start = self._start_index()
        earliest = max(start, self._pairing_floor(history))
        # 从“丢掉最早一条”开始：全部保留会回到未超预算的路径，不必在此判断。
        for kept_from in range(start + 1, earliest + 1):
            if self.estimator.estimate(
                [*self._system_message(), *history[kept_from:]]
            ) <= self.token_budget:
                return kept_from
        if start and len(history) > 1:
            return start
        return earliest

    def _pairing_floor(self, history: Sequence[dict[str, Any]]) -> int:
        """返回允许裁剪到的最早下标：不切断尾部工具结果与其助手消息。

        尾部没有工具结果时至少保留最后一条消息，避免裁剪出空请求。
        """
        tool_results = 0
        for message in reversed(history):
            if str(message.get("role")) != MessageRole.TOOL.value:
                break
            tool_results += 1
        protected = tool_results + 1 if tool_results else 1
        return len(history) - protected

    def _pairing_floor(self, history: Sequence[dict[str, Any]]) -> int:
        """返回允许裁剪到的最早下标：不切断尾部工具结果与其助手消息。"""
        tool_results = 0
        for message in reversed(history):
            if str(message.get("role")) != MessageRole.TOOL.value:
                break
            tool_results += 1
        protected = tool_results + 1 if tool_results else 1
        return len(history) - protected

    def _preview(self, removed: Sequence[dict[str, Any]]) -> str:
        """返回被移除内容的安全预览：只取文本、按字符截断。"""
        parts = [
            str(message.get("content") or "").strip()
            for message in removed
            if str(message.get("role")) != MessageRole.TOOL.value
        ]
        return " ".join(part for part in parts if part)[:PREVIEW_LIMIT]
