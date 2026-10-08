"""ContextWindow 兼容适配器。build 保留软预算；模型入口实行硬预算。"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .config import DEFAULT_TOKEN_BUDGET, PREVIEW_LIMIT
from .contracts import ContextBudgetExceededError, ContextError
from .estimator import HeuristicTokenEstimator, TokenEstimator
from .records import CompressionRecord, WindowBuild
from .reduction import WindowReducer
from .validation import count_tokens, validate_message


@dataclass
class ContextWindow:
    token_budget: int = DEFAULT_TOKEN_BUDGET
    estimator: TokenEstimator = field(default_factory=HeuristicTokenEstimator)
    system_prompt: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    _last_compression: CompressionRecord | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.token_budget) is not int or self.token_budget < 1:
            raise ValueError("token_budget 必须是正整数")

    def add(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def build(self) -> WindowBuild:
        systems = [] if self.system_prompt is None else [{"role": "system", "content": self.system_prompt}]
        result = WindowReducer(self.estimator, self.token_budget, soft=True).reduce(systems + self.messages)
        self.messages = deepcopy(result.messages[len(systems):])
        self._last_compression = result.compression
        return result

    def get_windowed_messages(self) -> list[dict[str, Any]]:
        result = self.build()
        if count_tokens(self.estimator, result.messages) > self.token_budget:
            raise ContextBudgetExceededError("旧窗口的软预算结果不能作为超限模型请求")
        return deepcopy(result.messages)

    @property
    def last_compression(self) -> CompressionRecord | None:
        return self._last_compression

    def snapshot_state(self) -> dict[str, Any]:
        return deepcopy({"kind": "window", "token_budget": self.token_budget,
                         "system_prompt": self.system_prompt, "messages": self.messages})

    def restore_state(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or set(data) != {"kind", "token_budget", "system_prompt", "messages"} or data["kind"] != "window" or data["token_budget"] != self.token_budget or data["system_prompt"] != self.system_prompt or not isinstance(data["messages"], list):
            raise ContextError("上下文快照配置不匹配")
        self.messages = [validate_message(m) for m in data["messages"]]
        self._last_compression = None
