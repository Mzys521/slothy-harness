"""智能体运行器使用的、提供方中立的工具契约。"""

from dataclasses import dataclass, field
from json import dumps
from math import isfinite
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ToolContext:
    """一次执行的上下文，只携带工具可以安全使用的标识信息。"""

    run_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    #: 策略计算的本次尝试剩余时限；执行器可据此设置底层 I/O 超时。
    timeout_seconds: float | None = None
    idempotency_key: str = ""
    request_fingerprint: str = ""
    approval_id: str = ""

    def __post_init__(self) -> None:
        value = self.timeout_seconds
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value <= 0
        ):
            raise ValueError("timeout_seconds 必须是有限的正数")
        if any(not isinstance(value, str) for value in (
            self.idempotency_key, self.request_fingerprint, self.approval_id,
        )) or (bool(self.idempotency_key) != bool(self.request_fingerprint)):
            raise ValueError("幂等键和指纹必须配对且为字符串")


@dataclass(frozen=True)
class ToolResult:
    output: Any
    is_error: bool = False

    def to_model_output(self) -> str:
        return dumps(
            {"output": self.output, "is_error": self.is_error},
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class ProgressReport:
    """长任务执行器上报的一次进度。

    只包含计数、阶段名和短文本：进度会进入事件并可能显示在界面上，因此不得
    携带密钥、工具参数取值或结果内容。
    """

    completed: int = 0
    total: int | None = None
    message: str = ""


class ToolRegistry(Protocol):
    def definitions(self) -> list[dict[str, Any]]:
        """返回供模型提供方转换的工具定义。"""
        ...

