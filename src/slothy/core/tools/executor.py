"""核心层的工具执行器抽象契约。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slothy.core.model.model_models import ToolCall
    from .tool_models import ProgressReport, ToolContext, ToolResult

#: 执行器上报进度时调用的回调；进度由工具模块转换为 ``ToolProgress`` 事件。
ProgressCallback = Callable[["ProgressReport"], None]


class ToolExecutor(ABC):
    """受控执行工具调用的抽象基类。

    具体实现必须完成参数校验、权限判断和结果封装。工具模块的调用入口依赖本
    契约，运行器不直接调用工具处理函数。
    """

    @abstractmethod
    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: ProgressCallback | None = None,
    ) -> ToolResult:
        """处理一次工具调用并返回可反馈给模型的结果。

        ``on_progress`` 是可选的进度回调。长任务执行器可以在执行过程中多次
        调用它，工具模块随即发出 ``ToolProgress`` 事件；执行器也可以忽略它。
        回调只接受 :class:`ProgressReport`，不得携带工具参数或结果内容。
        """
