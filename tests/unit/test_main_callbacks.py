"""主入口工具调用回调的测试。

使用假模型和假执行器，不访问网络。
"""

import unittest
from contextlib import redirect_stdout
from io import StringIO
from typing import Any

from slothy.core.events import EventBus, RunTimeline, ToolCallEnd
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import PolicyEngine, PolicyVerdict, ToolNameRule
from slothy.main import ToolReporter, run_calculation


class ScriptedModel(ModelProvider):
    """按脚本返回模型响应。"""

    def __init__(self, responses: list[ModelResult]) -> None:
        self._responses = iter(responses)

    def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> ModelResult:
        return next(self._responses)


def call(name: str, call_id: str = "call-1") -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments={"a": 1.0, "b": 2.0})


def answering_model(requests: list[ToolCall] | None = None) -> ScriptedModel:
    """先请求给定的工具调用，再给出最终回答。"""
    return ScriptedModel(
        [
            ModelResult(tool_calls=requests or [call("add")]),
            ModelResult(text="完成"),
        ]
    )


class ToolReporterTests(unittest.TestCase):
    def test_reports_running_and_success(self) -> None:
        stream = StringIO()
        bus = EventBus()
        ToolReporter(stream).attach(bus)

        result = run_calculation(
            "1 + 2", model=answering_model(), events=bus, watch_tools=False
        )

        self.assertEqual(result.output, "完成")
        self.assertEqual(
            stream.getvalue().splitlines(),
            ["[tool running] add", "[tool run success] add"],
        )

    def test_reports_failed_tool(self) -> None:
        stream = StringIO()
        bus = EventBus()
        ToolReporter(stream).attach(bus)

        # 除数为零时执行器返回错误结果，工具调用本身完成但结果是错误。
        run_calculation(
            "1 / 0",
            model=answering_model(
                [ToolCall("call-1", "divide", {"a": 1.0, "b": 0.0})]
            ),
            events=bus,
            watch_tools=False,
        )

        self.assertEqual(
            stream.getvalue().splitlines(),
            ["[tool running] divide", "[tool run failed] divide"],
        )

    def test_reports_each_tool_call_separately(self) -> None:
        stream = StringIO()
        bus = EventBus()
        ToolReporter(stream).attach(bus)

        run_calculation(
            "计算",
            model=answering_model(
                [call("add", "call-1"), call("multiply", "call-2")]
            ),
            events=bus,
            watch_tools=False,
        )

        self.assertEqual(
            stream.getvalue().splitlines(),
            [
                "[tool running] add",
                "[tool run success] add",
                "[tool running] multiply",
                "[tool run success] multiply",
            ],
        )

    def test_blocked_call_reports_blocked_without_failure_line(self) -> None:
        stream = StringIO()
        bus = EventBus()
        ToolReporter(stream).attach(bus)
        policy = PolicyEngine(rules=(ToolNameRule("add", PolicyVerdict.DENY),))

        result = run_calculation(
            "1 + 2",
            model=answering_model(),
            policy=policy,
            events=bus,
            watch_tools=False,
        )

        self.assertEqual(result.output, "完成")
        self.assertEqual(
            stream.getvalue().splitlines(),
            ["[tool running] add", "[tool blocked] add"],
        )

    def test_watch_tools_uses_stdout_by_default(self) -> None:
        stream = StringIO()

        with redirect_stdout(stream):
            run_calculation("1 + 2", model=answering_model())

        self.assertEqual(
            stream.getvalue().splitlines(),
            ["[tool running] add", "[tool run success] add"],
        )

    def test_watch_tools_can_be_disabled(self) -> None:
        stream = StringIO()

        with redirect_stdout(stream):
            run_calculation("1 + 2", model=answering_model(), watch_tools=False)

        self.assertEqual(stream.getvalue(), "")

    def test_reporting_does_not_change_the_result(self) -> None:
        quiet = run_calculation("1 + 2", model=answering_model(), watch_tools=False)
        stream = StringIO()
        with redirect_stdout(stream):
            reported = run_calculation("1 + 2", model=answering_model())

        self.assertEqual(quiet.output, reported.output)
        self.assertEqual(quiet.steps, reported.steps)
        self.assertNotEqual(stream.getvalue(), "")

    def test_reporting_preserves_a_non_bus_event_sink(self) -> None:
        timeline = RunTimeline()
        with redirect_stdout(StringIO()):
            run_calculation("1 + 2", model=answering_model(), events=timeline)
        self.assertEqual(len(timeline.of_type(ToolCallEnd)), 1)

    def test_reporting_subscription_does_not_accumulate_on_shared_bus(self) -> None:
        bus, stream = EventBus(), StringIO()
        with redirect_stdout(stream):
            run_calculation("first", model=answering_model(), events=bus)
            run_calculation("second", model=answering_model(), events=bus)
        self.assertEqual(len(stream.getvalue().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
