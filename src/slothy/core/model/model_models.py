"""厂商无关的模型数据契约（核心层）。

这些类型描述 Harness 与语言模型之间的交换，不包含任何厂商特有的细节，
因此属于核心层。基础设施层中的具体提供方根据其原生响应构造这些值。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelUsage:
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(
        self,
        other: "ModelUsage",
    ) -> "ModelUsage":
        return ModelUsage(
            total_tokens=(
                self.total_tokens
                + other.total_tokens
            ),
            prompt_tokens=(
                self.prompt_tokens
                + other.prompt_tokens
            ),
            completion_tokens=(
                self.completion_tokens
                + other.completion_tokens
            ),
        )


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(
        default_factory=list
    )
    # response_id: str | None = None
    usage: ModelUsage = field(
        default_factory=ModelUsage
    )
    # cache_usage_reported: bool = False
