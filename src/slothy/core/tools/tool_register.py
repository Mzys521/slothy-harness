"""工具定义注册表。

本模块只保存并公布模型可见的工具定义，不负责执行工具。模型提出调用后，
参数校验、权限判断及实际执行仍须由 ``ToolExecutor`` 完成。
"""

from copy import deepcopy
from dataclasses import replace
from json import dumps
from typing import Any, Callable, Iterable, Mapping

from .tool_models import ToolRegistry

from .tool_definition import ToolDefinition
from .tooling import get_declared_tool


class ToolRegistry(ToolRegistry):
    """实现核心层 ``ToolRegistry`` 契约的内存注册表。

    注册表保持插入顺序，便于模型请求和测试得到稳定的工具定义列表。
    所有输入和输出都复制一份，调用方无法绕过注册流程修改已注册内容。
    """

    def __init__(self) -> None:
        """初始化空的工具定义集合。"""
        self._definitions: dict[str, dict[str, Any]] = {}
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        tool: (
            ToolDefinition
            | Callable[..., Any]
            | str
            | list[ToolDefinition | Callable[..., Any]]
            | tuple[ToolDefinition | Callable[..., Any], ...]
            | None
        ) = None,
        description: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        *,
        name: str | None = None,
    ) -> None:
        """注册工具对象、``@tool`` 函数、工具列表或原有三参数定义。

        工具对象及装饰过的函数会连同处理函数保存在注册表内；三参数方式
        仅保存模型可见的定义。``parameters`` 使用以对象为根的 JSON Schema。
        注册时只检查定义结构；调用参数的完整校验由执行器完成。

        参数：
            tool: 工具对象、``@tool`` 函数、二者组成的列表，或工具名称。
            description: 三参数方式中的工具说明。
            parameters: 三参数方式中的 JSON Schema 对象。
            name: 兼容旧接口的关键字形式工具名称。

        异常：
            ValueError: 名称或描述为空、参数结构无效，或名称已注册。
            TypeError: 参数类型不符合工具定义契约。
        """
        if name is not None:
            if tool is not None:
                raise TypeError("tool 与 name 不能同时指定")
            tool = name
        if tool is None:
            raise TypeError("必须提供工具对象或工具名称")

        if isinstance(tool, (list, tuple)):
            if description is not None or parameters is not None:
                raise TypeError("批量注册时无需另传 description 或 parameters")
            self.register_many(tool)
            return

        registered_tool: ToolDefinition | None = None
        if isinstance(tool, ToolDefinition):
            registered_tool = tool
        elif callable(tool):
            registered_tool = get_declared_tool(tool)
            if registered_tool is None:
                raise TypeError("可调用对象必须先使用 @tool 声明")

        if registered_tool is not None:
            if description is not None or parameters is not None:
                raise TypeError("注册工具对象时无需另传 description 或 parameters")
            name = registered_tool.name
            description = registered_tool.description
            parameters = registered_tool.parameters
        else:
            name = tool
            if description is None or parameters is None:
                raise TypeError("三参数注册方式需要 name、description 和 parameters")

        if not isinstance(name, str):
            raise TypeError("工具名称必须是字符串")
        if (
            not name
            or not name.isascii()
            or len(name) > 64
            or not all(character.isalnum() or character in "_-" for character in name)
        ):
            raise ValueError(
                "工具名称必须由 1 至 64 个 ASCII 字母、数字、下划线或连字符组成"
            )
        if not isinstance(description, str):
            raise TypeError("工具描述必须是字符串")
        if not description.strip():
            raise ValueError("工具描述不能为空")
        if not isinstance(parameters, Mapping):
            raise TypeError("工具参数定义必须是映射")
        if parameters.get("type") != "object":
            raise ValueError("工具参数定义的根类型必须是 object")

        # 不实现完整 JSON Schema 解析，但拒绝常见的自相矛盾结构。
        properties = parameters.get("properties", {})
        if not isinstance(properties, Mapping) or not all(
            isinstance(key, str) and isinstance(value, Mapping)
            for key, value in properties.items()
        ):
            raise ValueError("properties 必须是属性名到属性定义的映射")
        required = parameters.get("required", [])
        if (
            not isinstance(required, list)
            or not all(isinstance(key, str) and key in properties for key in required)
            or len(required) != len(set(required))
        ):
            raise ValueError(
                "required 必须是无重复且已在 properties 中声明的属性名列表"
            )
        if name in self._definitions:
            raise ValueError(f"工具已注册：{name}")

        # 模型提供方需要可编码为 JSON 的结构，注册时就阻止不可序列化的值。
        copied_parameters = deepcopy(dict(parameters))
        try:
            dumps(copied_parameters, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("工具参数定义必须可序列化为 JSON") from exc

        # 先准备全部副本，再写入注册表，避免复制失败后只留下部分状态。
        stored_tool = (
            replace(registered_tool, parameters=deepcopy(copied_parameters))
            if registered_tool is not None
            else None
        )
        self._definitions[name] = {
            "name": name,
            "description": description,
            "parameters": copied_parameters,
        }
        if stored_tool is not None:
            # 保留处理函数供受控执行器查找，同时隔离原工具对象中的可变 schema。
            self._tools[name] = stored_tool

    def register_many(
        self, tools: Iterable[ToolDefinition | Callable[..., Any]]
    ) -> None:
        """批量注册工具；任意一项失败时撤销本批次已添加的工具。"""
        added_names: list[str] = []
        try:
            for candidate in tools:
                definition = (
                    candidate
                    if isinstance(candidate, ToolDefinition)
                    else get_declared_tool(candidate) if callable(candidate) else None
                )
                if definition is None:
                    raise TypeError("批量注册仅接受工具对象或 @tool 函数")
                self.register(candidate)
                added_names.append(definition.name)
        except Exception:
            for name in reversed(added_names):
                self.unregister(name)
            raise

    def unregister(self, name: str) -> bool:
        """移除指定工具；若名称不存在则返回 ``False``。"""
        self._tools.pop(name, None)
        return self._definitions.pop(name, None) is not None

    def get(self, name: str) -> dict[str, Any] | None:
        """返回指定工具定义的副本；未注册时返回 ``None``。"""
        definition = self._definitions.get(name)
        return deepcopy(definition) if definition is not None else None

    def get_tool(self, name: str) -> ToolDefinition | None:
        """返回已注册工具对象的副本，供受控执行器使用。"""
        registered_tool = self._tools.get(name)
        if registered_tool is None:
            return None
        return replace(registered_tool, parameters=deepcopy(registered_tool.parameters))

    def definitions(self) -> list[dict[str, Any]]:
        """按注册顺序返回独立副本，供模型提供方转换。"""
        return deepcopy(list(self._definitions.values()))


# 兼容此前的类名，避免已存在的调用方和测试因重命名中断。
ToolRegister = ToolRegistry
