"""模型/工具循环的行为测试。"""

import json
import unittest
from copy import deepcopy

from slothy.core.runtime.runner import AgentRunner
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.runtime import Run, RunCancelledError, RunStatus, StepStatus
from slothy.core.tools import ToolContext, ToolResult


class FakeModel(ModelProvider):
    def __init__(self, responses: list[ModelResult]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[list[dict], dict]] = []

    def generate(self, messages: list[dict], **kwargs: object) -> ModelResult:
        self.requests.append((deepcopy(messages), dict(kwargs)))
        return next(self.responses)


class FakeRegistry:
    def definitions(self) -> list[dict]:
        return [{"name": "lookup", "description": "Find a value"}]


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[ToolCall, ToolContext]] = []

    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: object = None,
    ) -> ToolResult:
        self.calls.append((call, context))
        return ToolResult(output={"value": 42})


class AgentRunnerTests(unittest.TestCase):
    def test_direct_answer_uses_one_step(self) -> None:
        model = FakeModel([ModelResult(text="done")])
        executor = FakeExecutor()
        context = ToolContext(run_id="run-1")

        result = AgentRunner(model, FakeRegistry(), executor).run(
            "question", context=context
        )

        self.assertEqual((result.output, result.steps), ("done", 1))
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(result.run.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(model.requests[0][0], [{"role": "user", "content": "question"}])
        self.assertEqual(model.requests[0][1]["tools"], FakeRegistry().definitions())
        self.assertEqual(executor.calls, [])

    def test_tool_result_is_returned_to_model_with_call_id(self) -> None:
        call = ToolCall(call_id="call-1", name="lookup", arguments={"key": "x"})
        model = FakeModel(
            [ModelResult(tool_calls=[call]), ModelResult(text="The value is 42")]
        )
        executor = FakeExecutor()
        context = ToolContext(run_id="run-2")

        result = AgentRunner(model, FakeRegistry(), executor).run(
            "find x", context=context
        )

        self.assertEqual((result.output, result.steps), ("The value is 42", 2))
        self.assertEqual(result.run.steps[0].tool_call_ids, ["call-1"])
        self.assertEqual(executor.calls, [(call, context)])
        follow_up = model.requests[1][0]
        self.assertEqual(follow_up[1]["tool_calls"][0]["call_id"], "call-1")
        self.assertEqual(follow_up[2]["call_id"], "call-1")
        self.assertEqual(
            json.loads(follow_up[2]["content"]),
            {"output": {"value": 42}, "is_error": False},
        )

    def test_step_limit_prevents_unusable_tool_execution(self) -> None:
        call = ToolCall(call_id="call-1", name="lookup", arguments={})
        model = FakeModel([ModelResult(tool_calls=[call])])
        executor = FakeExecutor()
        runtime = Run(run_id="run-3", max_steps=1)

        with self.assertRaisesRegex(RuntimeError, "Exceeded max steps \\(1\\)"):
            AgentRunner(model, FakeRegistry(), executor, max_steps=1).run(
                "question", context=ToolContext(run_id="run-3"), runtime=runtime
            )

        self.assertEqual(len(model.requests), 1)
        self.assertEqual(executor.calls, [])
        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.steps[0].status, StepStatus.FAILED)

    def test_cancellation_stops_before_tool_execution(self) -> None:
        runtime = Run(run_id="run-cancel", max_steps=8)

        class CancellingModel(ModelProvider):
            def generate(self, messages: list[dict], **kwargs: object) -> ModelResult:
                runtime.cancel()
                return ModelResult(
                    tool_calls=[ToolCall("call-1", "lookup", {"key": "x"})]
                )

        executor = FakeExecutor()
        with self.assertRaises(RunCancelledError):
            AgentRunner(CancellingModel(), FakeRegistry(), executor).run(
                "question",
                context=ToolContext(run_id="run-cancel"),
                runtime=runtime,
            )

        self.assertEqual(executor.calls, [])
        self.assertEqual(runtime.status, RunStatus.CANCELLED)
        self.assertEqual(runtime.steps[0].status, StepStatus.CANCELLED)

    def test_cancellation_after_tool_stops_follow_up_model_call(self) -> None:
        runtime = Run(run_id="run-tool-cancel", max_steps=8)
        call = ToolCall("call-1", "lookup", {"key": "x"})
        model = FakeModel([ModelResult(tool_calls=[call])])

        class CancellingExecutor(FakeExecutor):
            def execute(
                self,
                call: ToolCall,
                context: ToolContext,
                on_progress: object = None,
            ) -> ToolResult:
                runtime.cancel()
                return super().execute(call, context, on_progress)

        executor = CancellingExecutor()
        with self.assertRaises(RunCancelledError):
            AgentRunner(model, FakeRegistry(), executor).run(
                "question",
                context=ToolContext(run_id="run-tool-cancel"),
                runtime=runtime,
            )

        self.assertEqual(len(model.requests), 1)
        self.assertEqual(runtime.status, RunStatus.CANCELLED)

    def test_registry_error_marks_run_failed(self) -> None:
        runtime = Run(run_id="run-registry-error", max_steps=8)

        class FailingRegistry:
            def definitions(self) -> list[dict]:
                raise ValueError("定义读取失败")

        with self.assertRaisesRegex(ValueError, "定义读取失败"):
            AgentRunner(FakeModel([]), FailingRegistry(), FakeExecutor()).run(
                "question",
                context=ToolContext(run_id="run-registry-error"),
                runtime=runtime,
            )

        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.steps, [])

    def test_invalid_step_limit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_steps"):
            AgentRunner(FakeModel([]), FakeRegistry(), FakeExecutor(), max_steps=0)


if __name__ == "__main__":
    unittest.main()
