"""核心层的工具执行器抽象契约。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slothy.core.model.model_models import ToolCall
    from .tool_models import ToolContext, ToolResult


class ToolExecutor(ABC):
    """受控执行工具调用的抽象基类。

    具体实现必须完成参数校验、权限判断和结果封装。核心运行器仅依赖本
    契约，不直接调用工具处理函数。
    """

    @abstractmethod
    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """处理一次工具调用并返回可反馈给模型的结果。"""
