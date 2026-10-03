"""工具定义注册表的核心层单元测试。"""

import unittest

from pydantic import BaseModel, ConfigDict, ValidationError

from slothy.core.tools import ToolRegister, tool, tool_from_pydantic


class AddArgs(BaseModel):
    """模拟用户定义的严格加法参数。"""

    model_config = ConfigDict(extra="forbid")
    a: float
    b: float


def add(a: float, b: float) -> float:
    """计算两个数字加法。"""
    return a + b


class ToolRegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegister()
        self.parameters = {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        }

    def test_definitions_keep_order_and_do_not_expose_internal_state(self) -> None:
        self.registry.register("lookup", "查找数据", self.parameters)
        self.registry.register("ping", "检查状态", {"type": "object"})

        self.parameters["properties"]["key"]["type"] = "number"
        definitions = self.registry.definitions()
        self.assertEqual([item["name"] for item in definitions], ["lookup", "ping"])
        self.assertEqual(
            definitions[0]["parameters"]["properties"]["key"]["type"],
            "string",
        )

        definitions[0]["parameters"]["required"].clear()
        found = self.registry.get("lookup")
        self.assertEqual(found["parameters"]["required"], ["key"])
        found["description"] = "已修改"
        self.assertEqual(self.registry.get("lookup")["description"], "查找数据")

    def test_duplicate_registration_and_removal(self) -> None:
        self.registry.register("lookup", "查找数据", self.parameters)
        with self.assertRaisesRegex(ValueError, "已注册"):
            self.registry.register("lookup", "重复", self.parameters)

        self.assertTrue(self.registry.unregister("lookup"))
        self.assertFalse(self.registry.unregister("lookup"))
        self.assertIsNone(self.registry.get("lookup"))
        self.registry.register("lookup", "重新注册", self.parameters)
        self.assertEqual(len(self.registry.definitions()), 1)

    def test_legacy_keyword_registration_is_supported(self) -> None:
        """旧接口的关键字参数调用仍能注册模型定义。"""
        self.registry.register(
            name="lookup", description="查找数据", parameters=self.parameters
        )
        self.assertEqual(self.registry.get("lookup")["description"], "查找数据")
        self.assertIsNone(self.registry.get_tool("lookup"))

    def test_invalid_definition_is_rejected(self) -> None:
        invalid_cases = (
            ("", "描述", self.parameters),
            ("bad name", "描述", self.parameters),
            ("lookup", "  ", self.parameters),
            ("lookup", "描述", {"type": "array"}),
            ("lookup", "描述", {"type": "object", "required": ["missing"]}),
            ("lookup", "描述", {"type": "object", "properties": {"x": {}}, "required": ["x", "x"]}),
            ("lookup", "描述", {"type": "object", "properties": {"x": {"default": object()}}}),
        )
        for name, description, parameters in invalid_cases:
            with self.subTest(name=name, description=description, parameters=parameters):
                with self.assertRaises(ValueError):
                    self.registry.register(name, description, parameters)
        self.assertEqual(self.registry.definitions(), [])

    def test_register_pydantic_tool_object(self) -> None:
        """工具对象可直接注册，模型定义中不暴露处理函数。"""
        calculator_tool = tool_from_pydantic(
            name="add",
            description="计算两个数字加法",
            args_model=AddArgs,
            handler=add,
            timeout_seconds=2.0,
        )
        self.registry.register(calculator_tool)

        definition = self.registry.definitions()[0]
        self.assertEqual(definition["name"], "add")
        self.assertEqual(definition["parameters"]["required"], ["a", "b"])
        self.assertIs(definition["parameters"]["additionalProperties"], False)
        self.assertNotIn("handler", definition)

        registered = self.registry.get_tool("add")
        self.assertIs(registered.handler, add)
        self.assertEqual(registered.timeout_seconds, 2.0)
        with self.assertRaises(ValidationError):
            registered.args_model.model_validate({"a": 1, "b": 2, "extra": 3})

        calculator_tool.parameters["properties"].clear()
        registered.parameters["properties"].clear()
        self.assertEqual(len(self.registry.definitions()[0]["parameters"]["properties"]), 2)

    def test_register_tool_list_rolls_back_on_duplicate(self) -> None:
        """列表可直接注册，发生重复时不留下部分注册结果。"""
        first = tool_from_pydantic(
            name="add", description="加法", args_model=AddArgs, handler=add
        )
        second = tool_from_pydantic(
            name="add", description="重复", args_model=AddArgs, handler=add
        )

        with self.assertRaisesRegex(ValueError, "已注册"):
            self.registry.register([first, second])
        self.assertEqual(self.registry.definitions(), [])

        self.registry.register([first])
        self.assertEqual(self.registry.definitions()[0]["name"], "add")

    def test_decorated_function_stays_callable_and_registers(self) -> None:
        """装饰器保留函数行为，注册时自动读取其工具定义。"""

        @tool
        def add_tool(a: float, b: float) -> float:
            """两数相加。"""
            return a + b

        self.assertEqual(add_tool(1, 2), 3)
        self.registry.register(add_tool)
        self.assertEqual(self.registry.definitions()[0]["name"], "add_tool")
        self.assertEqual(
            self.registry.definitions()[0]["parameters"]["required"],
            ["a", "b"],
        )
        self.assertIs(self.registry.get_tool("add_tool").handler, add_tool)

    def test_invalid_factory_arguments_and_undecorated_function(self) -> None:
        """尽早拒绝无法按参数模型调用的处理函数。"""
        with self.assertRaisesRegex(ValueError, "不匹配"):
            tool_from_pydantic(
                name="bad", description="错误", args_model=AddArgs, handler=lambda a: a
            )
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            tool_from_pydantic(
                name="bad",
                description="错误",
                args_model=AddArgs,
                handler=add,
                timeout_seconds=0,
            )
        with self.assertRaisesRegex(TypeError, "@tool"):
            self.registry.register(add)


if __name__ == "__main__":
    unittest.main()
