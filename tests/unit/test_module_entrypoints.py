"""模块入口独立工作、重复 Run 隔离与调用边界失败的回归测试。"""

import json
import unittest
from copy import deepcopy

from slothy.core.context import ContextWindow
from slothy.core.context.conversation import add
from slothy.core.events import (
    ContextCompressed,
    Metric,
    ModelResponded,
    RunFailed,
    RunTimeline,
    TokenChunk,
    TokenUsage,
    ToolCallEnd,
    ToolProgress,
)
from slothy.core.events.emitter import EventEmitter
from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from slothy.core.model.session import ModelSession
from slothy.core.policy import PolicyEngine
from slothy.core.runtime import AgentRunner, Run, RunCancelledError, RunStatus
from slothy.core.tools import ProgressReport, ToolContext, ToolResult
from slothy.core.tools.session import ToolSession


class Registry:
    def definitions(self):
        return [{"name": "lookup", "description": "查找"}]


class StreamingModel(ModelProvider):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        if kwargs.get("on_chunk") is not None:
            kwargs["on_chunk"]("片段")
        return next(self.responses)


class Executor:
    def execute(self, call, context, on_progress=None):
        return ToolResult(output=42)


class ModuleEntrypointTests(unittest.TestCase):
    def test_context_entrypoint_keeps_complete_tool_exchange_when_trimming(self):
        events = []
        emitter = EventEmitter(events.append, enabled=True)
        window = ContextWindow(token_budget=100, system_prompt="系统提示")
        conversation = add("历史消息" * 100, window=window, events=emitter)
        call = ToolCall("call-1", "lookup", {"key": "x"})
        response = ModelResult(text="正在查找", tool_calls=[call])

        self.assertIs(add(response, conversation), conversation)
        add(ToolResult(output=42), conversation, call_id=call.call_id)
        messages = conversation.messages

        self.assertEqual([message["role"] for message in messages], [
            "system", "assistant", "tool"
        ])
        self.assertEqual(messages[1]["tool_calls"], [{
            "call_id": call.call_id, "name": call.name, "arguments": call.arguments
        }])
        self.assertEqual(json.loads(messages[2]["content"]), {
            "output": 42, "is_error": False
        })
        self.assertEqual(events[0].messages_removed, 1)
        self.assertIsInstance(events[0], ContextCompressed)
        self.assertEqual(conversation.messages, messages)
        self.assertEqual(len(events), 1)

    def test_tool_result_without_call_id_does_not_modify_conversation(self):
        conversation = add("问题")

        with self.assertRaisesRegex(ValueError, "call_id"):
            add(ToolResult(output=42), conversation)

        self.assertEqual(conversation.messages, [{"role": "user", "content": "问题"}])

    def test_existing_conversation_cannot_be_silently_reconfigured(self):
        conversation = add("问题")

        with self.assertRaisesRegex(ValueError, "重新配置"):
            add("后续问题", conversation, token_budget=100)

        self.assertEqual(conversation.messages, [{"role": "user", "content": "问题"}])

    def test_model_entrypoint_checks_cancellation_before_accounting_usage(self):
        events = []
        emitter = EventEmitter(events.append, enabled=True)
        model = StreamingModel([
            ModelResult(text="完成", usage=ModelUsage(total_tokens=5))
        ])

        checks = []

        def cancelled():
            checks.append(True)
            if len(checks) == 2:
                raise RuntimeError("cancelled")

        session = ModelSession(model, emitter, cancelled)
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            session.model_call([{"role": "user", "content": "问题"}], [])

        self.assertIsInstance(events[-1], ModelResponded)
        self.assertFalse(any(isinstance(event, TokenUsage) for event in events))

    def test_runner_reuse_starts_fresh_context_usage_and_chunk_indexes(self):
        usage = ModelUsage(total_tokens=5)
        model = StreamingModel([
            ModelResult(tool_calls=[ToolCall("call-1", "lookup", {})], usage=usage),
            ModelResult(text="第一次完成", usage=usage),
            ModelResult(text="第二次完成", usage=usage),
        ])
        runner = AgentRunner(model, Registry(), Executor())
        first, second = RunTimeline(), RunTimeline()

        runner.run("第一次", context=ToolContext("run-1"), events=first)
        result = runner.run("第二次", context=ToolContext("run-2"), events=second)

        self.assertEqual(result.output, "第二次完成")
        self.assertEqual(model.requests[2], [{"role": "user", "content": "第二次"}])
        self.assertEqual([event.index for event in first.of_type(TokenChunk)], [0, 1])
        self.assertEqual([event.index for event in second.of_type(TokenChunk)], [0])
        self.assertEqual(
            [event.cumulative.total_tokens for event in first.of_type(TokenUsage)],
            [5, 10],
        )
        self.assertEqual(
            [event.cumulative.total_tokens for event in second.of_type(TokenUsage)],
            [5],
        )
        self.assertEqual(
            [event.sequence for event in second.events],
            list(range(1, len(second.events) + 1)),
        )

    def test_explicit_window_remains_shared_with_the_caller(self):
        window = ContextWindow(system_prompt="系统提示", token_budget=10_000)
        window.add({"role": "user", "content": "调用方历史"})
        model = StreamingModel([ModelResult(text="完成")])
        runner = AgentRunner(model, Registry(), Executor(), context=window)

        runner.run("问题", context=ToolContext("run-shared"))

        self.assertEqual([message["content"] for message in model.requests[0]], [
            "系统提示", "调用方历史", "问题"
        ])
        self.assertEqual(window.messages[-1], {"role": "assistant", "content": "完成"})

    def test_old_progress_callback_stays_inactive_when_call_id_is_reused(self):
        events = []
        emitter = EventEmitter(events.append, enabled=True)
        callbacks = []

        class DelayedExecutor:
            def execute(self, call, context, on_progress=None):
                if callbacks:
                    callbacks[0](ProgressReport(completed=99))
                callbacks.append(on_progress)
                on_progress(ProgressReport(completed=len(callbacks)))
                return ToolResult(output=42)

        session = ToolSession(Registry(), DelayedExecutor(), PolicyEngine(), emitter)
        call = ToolCall("same-call-id", "lookup", {})
        session.tool_call(call, ToolContext("run-1"))
        session.tool_call(call, ToolContext("run-1"))
        callbacks[1](ProgressReport(completed=100))

        self.assertEqual(
            [event.completed for event in events if isinstance(event, ToolProgress)],
            [1, 2],
        )

    def test_progress_callback_is_disabled_on_executor_failure(self):
        events = []
        emitter = EventEmitter(events.append, enabled=True)
        callbacks = []
        error = ValueError("执行失败")

        class FailingExecutor:
            def execute(self, call, context, on_progress=None):
                callbacks.append(on_progress)
                raise error

        session = ToolSession(Registry(), FailingExecutor(), PolicyEngine(), emitter)
        with self.assertRaises(ValueError) as raised:
            session.tool_call(ToolCall("call-1", "lookup", {}), ToolContext("run-1"))
        callbacks[0](ProgressReport(completed=1))

        self.assertIs(raised.exception, error)
        self.assertEqual(events[-1].event_type, "run.tool.error")
        self.assertFalse(any(isinstance(event, ToolProgress) for event in events))
        self.assertFalse(any(isinstance(event, ToolCallEnd) for event in events))

    def test_cancelling_first_tool_prevents_remaining_batch_execution(self):
        runtime = Run("run-batch-cancel", max_steps=8)
        calls = []

        class CancellingExecutor:
            def execute(self, call, context, on_progress=None):
                calls.append(call.call_id)
                runtime.cancel()
                return ToolResult(output=42)

        model = StreamingModel([ModelResult(tool_calls=[
            ToolCall("call-1", "lookup", {}), ToolCall("call-2", "lookup", {})
        ])])
        runner = AgentRunner(model, Registry(), CancellingExecutor())
        with self.assertRaises(RunCancelledError):
            runner.run("问题", context=ToolContext(runtime.run_id), runtime=runtime)

        self.assertEqual(calls, ["call-1"])
        self.assertEqual(len(model.requests), 1)

    def test_context_initialization_failure_terminates_started_run(self):
        timeline = RunTimeline()
        runtime = Run("run-invalid-context", max_steps=8)
        model = StreamingModel([])
        runner = AgentRunner(model, Registry(), Executor(), token_budget=0)

        with self.assertRaisesRegex(ValueError, "token_budget"):
            runner.run(
                "问题", context=ToolContext(runtime.run_id),
                runtime=runtime, events=timeline,
            )

        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.steps, [])
        self.assertEqual(model.requests, [])
        self.assertEqual(len(timeline.of_type(RunFailed)), 1)
        self.assertEqual(
            [event.name for event in timeline.of_type(Metric)], ["run.duration_ms"]
        )


if __name__ == "__main__":
    unittest.main()
