"""稳定的窗口返回结构；与具体压缩实现无关。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompressionRecord:
    tokens_before: int
    tokens_after: int
    messages_removed: int
    strategy: str = "trim_oldest"
    preview: str = ""
    messages_truncated: int = 0


@dataclass(frozen=True)
class WindowBuild:
    messages: list[dict[str, Any]]
    compression: CompressionRecord | None = None
