"""MiMo 适配器的流式响应测试。

用假 SDK 对象验证分片拼装，不发起网络调用。
"""

import json
import unittest
from types import SimpleNamespace

from slothy.core.runtime import AgentRunner
from slothy.core.tools import ToolContext, ToolRegister, ToolResult, tool_from_pydantic
from slothy.infrastructure.llm.providers.mimo_provider import MimoProvider

from pydantic import BaseModel, ConfigDict


def chunk(*, content: str | None = None, tool_calls: list | None = None, usage=None):
    """构造一个流式分片。"""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta)] if content or tool_calls else [],
        usage=usage,
    )


def tool_delta(index: int, call_id: str | None, name: str | None, arguments: str):
    """构造一个工具调用分片。"""
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeStreamCompletions:
    """依次返回多轮预设流式分片，并记录 ``create`` 参数。"""

    def __init__(self, rounds: list[list]) -> None:
        self._rounds = iter(rounds)
        self.requests: list[dict] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(dict(kwargs))
        return iter(next(self._rounds))


class LookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str


def lookup(key: str) -> dict[str, int]:
    return {"value": 42}


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def execute(
        self, call: object, context: ToolContext, on_progress: object = None
    ) -> ToolResult:
        self.calls.append((call, context))
        return ToolResult(output={"value": 42})


def build_provider(rounds: list[list]) -> tuple[MimoProvider, FakeStreamCompletions]:
    provider = MimoProvider(
        api_key="test", base_url="https://example.test/v1", model="mimo"
    )
    completions = FakeStreamCompletions(rounds)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return provider, completions


class MimoStreamingTests(unittest.TestCase):
    def test_text_deltas_are_concatenated_and_reported(self) -> None:
        provider, completions = build_provider(
            [
                [
                    chunk(content="答案是"),
                    chunk(content=" 42"),
                    chunk(usage=SimpleNamespace(total_tokens=9, prompt_tokens=5, completion_tokens=4)),
                ]
            ]
        )
        received: list[str] = []

        result = provider.generate(
            [{"role": "user", "content": "问题"}], on_chunk=received.append
        )

        self.assertEqual(result.text, "答案是 42")
        self.assertEqual(received, ["答案是", " 42"])
        self.assertEqual(result.usage.total_tokens, 9)
        self.assertEqual(result.tool_calls, [])
        request = completions.requests[0]
        self.assertTrue(request["stream"])
        self.assertEqual(request["stream_options"], {"include_usage": True})
        self.assertNotIn("on_chunk", request)

    def test_fragmented_tool_call_is_assembled(self) -> None:
        provider, _ = build_provider(
            [
                [
                    chunk(
                        tool_calls=[tool_delta(0, "call-1", "lookup", '{"key"')]
                    ),
                    chunk(tool_calls=[tool_delta(0, None, None, ': "x"}')]),
                ]
            ]
        )

        result = provider.generate(
            [{"role": "user", "content": "问题"}], on_chunk=lambda text: None
        )

        self.assertEqual(len(result.tool_calls), 1)
        call = result.tool_calls[0]
        self.assertEqual(call.call_id, "call-1")
        self.assertEqual(call.name, "lookup")
        self.assertEqual(call.arguments, {"key": "x"})

    def test_multiple_tool_calls_stay_in_index_order(self) -> None:
        provider, _ = build_provider(
            [
                [
                    chunk(tool_calls=[tool_delta(1, "call-b", "second", "{}")]),
                    chunk(tool_calls=[tool_delta(0, "call-a", "first", "{}")]),
                ]
            ]
        )

        result = provider.generate(
            [{"role": "user", "content": "问题"}], on_chunk=lambda text: None
        )

        self.assertEqual(
            [(call.call_id, call.name) for call in result.tool_calls],
            [("call-a", "first"), ("call-b", "second")],
        )

    def test_missing_call_id_falls_back_to_index(self) -> None:
        provider, _ = build_provider(
            [[chunk(tool_calls=[tool_delta(2, None, "lookup", "{}")])]]
        )

        result = provider.generate(
            [{"role": "user", "content": "问题"}], on_chunk=lambda text: None
        )

        self.assertEqual(result.tool_calls[0].call_id, "call-2")

    def test_tool_definitions_are_converted_in_streaming_requests(self) -> None:
        provider, completions = build_provider([[chunk(content="完成")]])

        provider.generate(
            [{"role": "user", "content": "问题"}],
            tools=[{"name": "lookup", "description": "查找", "parameters": {}}],
            on_chunk=lambda text: None,
        )

        tools = completions.requests[0]["tools"]
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "lookup")


class MimoStreamingRunnerTests(unittest.TestCase):
    """运行器与流式提供方的契约：文本增量成为 TokenChunk。"""

    def test_runner_emits_token_chunks_and_completes(self) -> None:
        from slothy.core.events import RunTimeline, TokenChunk

        provider, _ = build_provider([[chunk(content="42")]])

        timeline = RunTimeline()
        result = AgentRunner(provider, ToolRegister(), FakeExecutor()).run(
            "问题", context=ToolContext(run_id="run-stream"), events=timeline
        )

        self.assertEqual((result.output, result.steps), ("42", 1))
        chunks = timeline.of_type(TokenChunk)
        self.assertEqual([(c.index, c.text) for c in chunks], [(0, "42")])

    def test_runner_streams_tool_round_trip(self) -> None:
        from slothy.core.events import RunTimeline, TokenChunk, ToolCallEnd

        provider = MimoProvider(
            api_key="test", base_url="https://example.test/v1", model="mimo"
        )
        completions = FakeStreamCompletions(
            [
                [
                    chunk(
                        tool_calls=[tool_delta(0, "call-1", "lookup", json.dumps({"key": "x"}))]
                    )
                ],
                [chunk(content="42")],
            ]
        )
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        registry = ToolRegister()
        registry.register(
            tool_from_pydantic(
                name="lookup",
                description="查找",
                args_model=LookupArgs,
                handler=lookup,
            )
        )
        executor = FakeExecutor()

        timeline = RunTimeline()
        result = AgentRunner(provider, registry, executor).run(
            "问题", context=ToolContext(run_id="run-stream-tool"), events=timeline
        )

        self.assertEqual((result.output, result.steps), ("42", 2))
        self.assertEqual(executor.calls[0][0].call_id, "call-1")
        self.assertEqual(len(timeline.of_type(TokenChunk)), 1)
        self.assertFalse(timeline.first(ToolCallEnd).is_error)
        # 两次请求都必须是流式，才能持续产生增量。
        self.assertTrue(all(request["stream"] for request in completions.requests))


if __name__ == "__main__":
    unittest.main()
