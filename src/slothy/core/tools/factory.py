"""从 Pydantic 参数模型创建工具定义。"""

from inspect import signature
from math import isfinite
from typing import Any, Callable

from pydantic import BaseModel

from .tool_definition import ToolDefinition


def tool_from_pydantic(
    *,
    name: str,
    description: str,
    args_model: type[BaseModel],
    handler: Callable[..., Any],
    timeout_seconds: float | None = None,
) -> ToolDefinition:
    """组合参数模型与处理函数，生成供注册表接收的工具对象。

    工厂只创建能力描述，不直接运行处理函数。实际调用时，执行器应先用
    ``args_model.model_validate`` 校验输入，再完成策略和权限检查，最后调用
    ``handler``；时限由执行器负责实施。
    """
    if not isinstance(args_model, type) or not issubclass(args_model, BaseModel):
        raise TypeError("args_model 必须是 Pydantic BaseModel 的子类")
    if not callable(handler):
        raise TypeError("handler 必须可调用")
    if timeout_seconds is not None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds 必须是有限的正数")

    # 执行器通过校验后的模型字段以关键字参数调用处理函数，提前检查接口匹配。
    try:
        signature(handler).bind(
            **{field_name: object() for field_name in args_model.model_fields}
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("handler 的参数与 args_model 字段不匹配") from exc

    return ToolDefinition(
        name=name,
        description=description,
        parameters=args_model.model_json_schema(),
        args_model=args_model,
        handler=handler,
        timeout_seconds=float(timeout_seconds) if timeout_seconds is not None else None,
    )
