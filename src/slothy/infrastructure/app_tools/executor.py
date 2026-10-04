"""仅执行已注册计算工具的受控执行器。"""

from math import isfinite
from typing import Any

from pydantic import ValidationError

from slothy.core.model import ToolCall
from slothy.core.tools import (
    ProgressCallback,
    ToolContext,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
)

from .calculator import tool_list


class CalculatorToolExecutor(ToolExecutor):
    """校验、授权并执行加减乘除和幂运算工具。

    允许列表来自本模块定义的计算工具。即使注册表后来出现同名的其他处理
    函数，也不会借此获得执行权限。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        """保存注册表及当前允许执行的处理函数。"""
        self.registry = registry
        self._allowed_handlers = {tool.name: tool.handler for tool in tool_list}

    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: ProgressCallback | None = None,
    ) -> ToolResult:
        """执行一次调用，并把可预期的错误作为工具结果返回。

        计算是瞬时操作，因此不接受 ``on_progress``：参数保留以符合执行器契约。
        """
        registered = self.registry.get_tool(call.name)
        if (
            registered is None
            or self._allowed_handlers.get(call.name) is not registered.handler
        ):
            return ToolResult(output={"error": "工具不存在或未获准执行"}, is_error=True)

        try:
            # 模型只提供参数请求；先按该工具的 Pydantic 模型完成校验。
            arguments = registered.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            details = [
                {"field": ".".join(map(str, error["loc"])), "message": error["msg"]}
                for error in exc.errors(include_input=False, include_url=False)
            ]
            return ToolResult(
                output={"error": "工具参数无效", "details": details},
                is_error=True,
            )

        try:
            value: Any = registered.handler(**arguments.model_dump())
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            return ToolResult(output={"error": str(exc)}, is_error=True)
        except Exception:
            # 未预料到的实现错误不向模型暴露内部异常或本地环境信息。
            return ToolResult(output={"error": "工具执行失败"}, is_error=True)

        if not isinstance(value, float) or not isfinite(value):
            return ToolResult(output={"error": "工具结果不是有限浮点数"}, is_error=True)
        return ToolResult(output=value)
