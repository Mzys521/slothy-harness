"""工具调用（Tool 级）事件。

工具模块在把模型请求交给受控执行器前后发出这些事件。参数只以 ``argument_keys``
的形式记录字段名，不携带取值；工具结果只记录大小，不记录原文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .base import ErrorInfo, RunCheckedError, RunEvent


class ToolCheckedError(RunCheckedError):
    """工具执行失败的分类基类，供执行器继承。"""

    error_code = "tool_error"


class ToolTimeoutError(ToolCheckedError, TimeoutError):
    """工具调用超时。

    执行器抛出本异常时，工具模块发出 ``ToolTimeout``；其他超时会被记为
    ``unexpected_timeout`` 以便排查未统一的调用方。
    """

    error_code = "tool_timeout"


@dataclass
class ToolEvent(RunEvent):
    """描述一次工具调用的事件，``call_id`` 对应模型给出的调用标识。"""

    EVENT_TYPE = "run.tool"

    call_id: str = ""


@dataclass
class ToolCallStart(ToolEvent):
    """工具模块已接收调用请求，即将进行策略判定与受控执行。"""

    EVENT_TYPE = "run.tool.call_started"

    name: str = ""
    argument_keys: Sequence[str] = field(default_factory=tuple)


@dataclass
class ToolCallEnd(ToolEvent):
    """工具模块已得到结果，包括执行器返回或策略拦截的错误结果。"""

    EVENT_TYPE = "run.tool.call_ended"

    name: str = ""
    duration_ms: float = 0.0
    is_error: bool = False
    output_size: int = 0


@dataclass
class ToolProgress(ToolEvent):
    """长任务的执行进度。

    由支持进度回调的执行器通过 ``ToolExecutor.execute(on_progress=...)`` 上报：
    执行器应在执行中多次调用回调，工具模块随即发出本事件。事件不携带工具参数或
    结果内容，只记录计数与阶段说明。
    """

    EVENT_TYPE = "run.tool.progress"

    name: str = ""
    completed: int = 0
    total: int | None = None
    message: str = ""


@dataclass
class ToolTimeout(ToolEvent):
    """工具调用超时，运行器随后进入失败终态。"""

    EVENT_TYPE = "run.tool.timeout"

    name: str = ""
    duration_ms: float = 0.0
    error: ErrorInfo | None = None


@dataclass
class ToolError(ToolEvent):
    """执行器抛出异常，工具调用未能返回结果。"""

    EVENT_TYPE = "run.tool.error"

    name: str = ""
    duration_ms: float = 0.0
    error: ErrorInfo | None = None
