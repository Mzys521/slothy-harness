"""主入口计算 Agent 的离线闭环测试。"""

import json
import unittest
from copy import deepcopy

from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.runtime import RunStatus
from slothy.core.tools import ToolContext, ToolRegistry
from slothy.infrastructure.app_tools import CalculatorToolExecutor, tool_list
from slothy.main import run_calculation


class ScriptedModel(ModelProvider):
    """依次返回指定模型响应，不访问网络。"""

    def __init__(self, responses: list[ModelResult]) -> None:
        self.responses = iter(responses)
        self.requests: list[list[dict]] = []

    def generate(self, messages: list[dict], **kwargs: object) -> ModelResult:
        self.requests.append(deepcopy(messages))
        return next(self.responses)


class MainCalculatorLoopTests(unittest.TestCase):
    def test_multi_round_calculation_returns_tool_results_to_model(self) -> None:
        """验证示例算式的连续工具调用和最终回答。"""
        operations = [
            ("power", {"a": 3.0, "b": 4.0}),
            ("divide", {"a": 81.0, "b": 15.0}),
            ("add", {"a": 2.0, "b": 5.4}),
            ("multiply", {"a": 16.0, "b": 4.0}),
            ("subtract", {"a": 64.0, "b": 2.0}),
            ("multiply", {"a": 7.4, "b": 62.0}),
        ]
        responses = [
            ModelResult(
                tool_calls=[
                    ToolCall(call_id=f"call-{index}", name=name, arguments=arguments)
                ]
            )
            for index, (name, arguments) in enumerate(operations, start=1)
        ]
        model = ScriptedModel([*responses, ModelResult(text="结果是 458.8")])

        result = run_calculation("计算示例算式", model=model)

        self.assertEqual((result.output, result.steps), ("结果是 458.8", 7))
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(len(result.run.steps), 7)
        tool_messages = [
            message
            for message in model.requests[-1]
            if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 6)
        values = [json.loads(message["content"])["output"] for message in tool_messages]
        for actual, expected in zip(values, [81.0, 5.4, 7.4, 64.0, 62.0, 458.8]):
            self.assertAlmostEqual(actual, expected)

    def test_executor_rejects_unknown_and_invalid_calls(self) -> None:
        """未知工具和错误参数以工具错误返回，不调用其他处理函数。"""
        registry = ToolRegistry()
        registry.register(tool_list)
        executor = CalculatorToolExecutor(registry)
        context = ToolContext(run_id="test-run")

        unknown = executor.execute(ToolCall("1", "shell", {}), context)
        invalid = executor.execute(
            ToolCall("2", "add", {"a": 1.0, "b": 2.0, "extra": 3.0}),
            context,
        )
        zero_division = executor.execute(
            ToolCall("3", "divide", {"a": 1.0, "b": 0.0}),
            context,
        )

        self.assertTrue(unknown.is_error)
        self.assertTrue(invalid.is_error)
        self.assertTrue(zero_division.is_error)
        self.assertIn("参数无效", invalid.output["error"])
        self.assertIn("除数", zero_division.output["error"])


if __name__ == "__main__":
    unittest.main()
