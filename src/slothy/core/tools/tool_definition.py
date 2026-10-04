"""带有参数模型和处理函数的工具定义。"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel
from .replay import ReplaySafety


@dataclass(frozen=True)
class ToolDefinition:
    """描述一个可注册的受控工具能力。

    ``handler`` 由未来的工具执行器在校验和授权后调用。注册表仅把
    ``name``、``description`` 和 ``parameters`` 提供给模型。
    ``timeout_seconds`` 是执行时限配置，注册表本身不执行计时。
    """

    name: str
    description: str
    parameters: dict[str, Any]
    args_model: type[BaseModel]
    handler: Callable[..., Any]
    timeout_seconds: float | None = None
    replay_safety: ReplaySafety = ReplaySafety.UNSPECIFIED
    execution_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.replay_safety, ReplaySafety):
            raise ValueError("replay_safety must be a ReplaySafety")
        if not isinstance(self.execution_version, str) or not self.execution_version:
            raise ValueError("execution_version must be a nonempty string")

    def model_definition(self) -> dict[str, Any]:
        """返回供模型提供方使用的定义副本，不暴露处理函数。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": deepcopy(self.parameters),
        }
