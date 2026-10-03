"""智能体运行器使用的、提供方中立的工具契约。"""

from dataclasses import dataclass, field
from json import dumps
from typing import Any, Mapping, Protocol

@dataclass(frozen=True)
class ToolContext:
    run_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    output: Any
    is_error: bool = False

    def to_model_output(self) -> str:
        return dumps(
            {"output": self.output, "is_error": self.is_error},
            ensure_ascii=False,
        )


class ToolRegistry(Protocol):
    def definitions(self) -> list[dict[str, Any]]:
        """返回供模型提供方转换的工具定义。"""
        ...


from .executor import ToolExecutor
