# 工具定义与注册

工具先由参数模型和处理函数组成，再交给 `ToolRegister` 注册。注册表向模型提供工具名称、描述和参数 schema，并保留处理函数供受控执行器查找。实际调用仍必须经过参数校验、策略和权限判断。

```python
from pydantic import BaseModel, ConfigDict

from slothy.core.tools import ToolRegister, tool, tool_from_pydantic


class AddArgs(BaseModel):
    """加法工具参数，不接收额外字段。"""

    model_config = ConfigDict(extra="forbid")
    a: float
    b: float


def add(a: float, b: float) -> float:
    """计算两个数字之和。"""
    return a + b


calculator_tool = tool_from_pydantic(
    name="add",
    description="计算两个数字加法",
    args_model=AddArgs,
    handler=add,
    timeout_seconds=2.0,
)


@tool
def subtract_tool(a: float, b: float) -> float:
    """计算两个数字减法。"""
    return a - b


registry = ToolRegister()
registry.register([calculator_tool, subtract_tool])

assert subtract_tool(5, 2) == 3  # 装饰后仍可作为普通函数调用
model_tools = registry.definitions()  # 传给模型提供方的工具定义
registered_add = registry.get_tool("add")  # 供受控执行器使用
```

`timeout_seconds` 目前保存在工具定义中；注册表不会执行工具，也不会自行实施超时。运行器仍通过独立的 `ToolExecutor` 完成校验、授权和调用。原有的 `register(name, description, parameters)` 方式继续可用，但它只注册模型可见的定义，没有处理函数。
