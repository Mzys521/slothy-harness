"""计算工具的具体定义，供应用按需注册。"""

from math import pow as real_pow

from pydantic import BaseModel, ConfigDict, Field

from slothy.core.tools import ToolDefinition, tool_from_pydantic


class AddArgs(BaseModel):
    """加法入参：两个浮点数，不接受额外字段或非有限数。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    a: float = Field(description="第一个加数")
    b: float = Field(description="第二个加数")


class SubtractArgs(BaseModel):
    """减法入参：浮点数被减数和减数。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    a: float = Field(description="被减数")
    b: float = Field(description="减数")


class MultiplyArgs(BaseModel):
    """乘法入参：两个浮点数乘数。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    a: float = Field(description="第一个乘数")
    b: float = Field(description="第二个乘数")


class DivideArgs(BaseModel):
    """除法入参：浮点数被除数和除数。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    a: float = Field(description="被除数")
    b: float = Field(description="除数，不能为 0")


class PowerArgs(BaseModel):
    """幂运算入参：浮点数底数和指数。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    a: float = Field(description="底数")
    b: float = Field(description="指数")


def add(a: float, b: float) -> float:
    """返回 a 与 b 的和。"""
    return float(a + b)


def subtract(a: float, b: float) -> float:
    """返回 a 减去 b 的结果。"""
    return float(a - b)


def multiply(a: float, b: float) -> float:
    """返回 a 与 b 的乘积。"""
    return float(a * b)


def divide(a: float, b: float) -> float:
    """返回 a 除以 b 的结果；除数为零时抛出 ``ValueError``。"""
    if b == 0:
        raise ValueError("除数不能为 0")
    return float(a / b)


def power(a: float, b: float) -> float:
    """返回 a 的 b 次幂；结果不是实数时抛出 ``ValueError``。"""
    try:
        # 使用实数幂运算，防止负底数的非整数次幂产生复数结果。
        return real_pow(a, b)
    except ValueError as exc:
        raise ValueError("底数与指数无法得到实数结果") from exc


# 以下对象仅定义工具能力；具体注册由应用在需要使用工具时完成。
add_tool: ToolDefinition = tool_from_pydantic(
    name="add",
    description="计算两个浮点数的和",
    args_model=AddArgs,
    handler=add,
    timeout_seconds=2.0,
)

subtract_tool: ToolDefinition = tool_from_pydantic(
    name="subtract",
    description="计算两个浮点数的差，即 a 减去 b",
    args_model=SubtractArgs,
    handler=subtract,
    timeout_seconds=2.0,
)

multiply_tool: ToolDefinition = tool_from_pydantic(
    name="multiply",
    description="计算两个浮点数的乘积",
    args_model=MultiplyArgs,
    handler=multiply,
    timeout_seconds=2.0,
)

divide_tool: ToolDefinition = tool_from_pydantic(
    name="divide",
    description="计算两个浮点数的商，即 a 除以 b；b 不能为 0",
    args_model=DivideArgs,
    handler=divide,
    timeout_seconds=2.0,
)

power_tool: ToolDefinition = tool_from_pydantic(
    name="power",
    description="计算浮点数 a 的 b 次幂，结果必须为实数",
    args_model=PowerArgs,
    handler=power,
    timeout_seconds=2.0,
)


# 保持固定顺序，调用方可以逐个使用 register(tool) 注册。
tool_list: list[ToolDefinition] = [
    add_tool,
    subtract_tool,
    multiply_tool,
    divide_tool,
    power_tool,
]
