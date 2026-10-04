"""保留普通函数调用方式的工具声明装饰器。"""

from inspect import Parameter, getdoc, signature
from typing import Any, Callable, TypeVar, get_type_hints, overload

from pydantic import ConfigDict, create_model

from .factory import tool_from_pydantic
from .tool_definition import ToolDefinition
from .replay import ReplaySafety


F = TypeVar("F", bound=Callable[..., Any])
TOOL_DEFINITION_ATTRIBUTE = "__slothy_tool_definition__"


@overload
def tool(function: F) -> F: ...


@overload
def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    timeout_seconds: float | None = None,
    replay_safety: ReplaySafety = ReplaySafety.UNSPECIFIED,
    execution_version: str = "1",
) -> Callable[[F], F]: ...


def tool(
    function: F | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    timeout_seconds: float | None = None,
    replay_safety: ReplaySafety = ReplaySafety.UNSPECIFIED,
    execution_version: str = "1",
) -> F | Callable[[F], F]:
    """从函数注解生成参数模型，并在函数上附加工具定义。

    可写 ``@tool`` 或 ``@tool(name="...", timeout_seconds=2.0)``。
    装饰器返回原函数，因此普通 Python 调用仍保持原来的行为。
    """

    def decorate(handler: F) -> F:
        """创建严格参数模型并把工具元数据附在原函数上。"""
        fields: dict[str, Any] = {}
        annotations = get_type_hints(handler)
        for parameter in signature(handler).parameters.values():
            if parameter.kind not in (
                Parameter.POSITIONAL_OR_KEYWORD,
                Parameter.KEYWORD_ONLY,
            ):
                raise TypeError("@tool 仅支持普通参数和仅关键字参数")
            annotation = annotations.get(parameter.name, parameter.annotation)
            if annotation is Parameter.empty:
                raise TypeError(f"工具参数缺少类型注解：{parameter.name}")
            default = ... if parameter.default is Parameter.empty else parameter.default
            fields[parameter.name] = (annotation, default)

        model = create_model(
            f"{handler.__name__}Args",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )
        definition = tool_from_pydantic(
            name=name or handler.__name__,
            description=description or getdoc(handler) or "",
            args_model=model,
            handler=handler,
            timeout_seconds=timeout_seconds,
            replay_safety=replay_safety,
            execution_version=execution_version,
        )
        setattr(handler, TOOL_DEFINITION_ATTRIBUTE, definition)
        return handler

    return decorate(function) if function is not None else decorate


def get_declared_tool(function: Callable[..., Any]) -> ToolDefinition | None:
    """读取 ``@tool`` 写入的定义；未声明时返回 ``None``。"""
    definition = getattr(function, TOOL_DEFINITION_ATTRIBUTE, None)
    return definition if isinstance(definition, ToolDefinition) else None
