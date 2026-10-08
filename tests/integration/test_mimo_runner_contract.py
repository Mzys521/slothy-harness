"""在不发起网络调用的情况下，使用 MiMo 适配器测试运行器。"""

import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict

from slothy.core.runtime.runner import AgentRunner
from slothy.core.tools import ToolContext, ToolRegister, ToolResult, tool_from_pydantic
from slothy.infrastructure.llm.providers.mimo_provider import MimoProvider


class FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="lookup", arguments='{"key":"x"}'),
        )
        self.responses = iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=None, tool_calls=[tool_call])
                        )
                    ],
                    usage=SimpleNamespace(
                        total_tokens=12, prompt_tokens=8, completion_tokens=4
                    ),
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="42", tool_calls=None)
                        )
                    ],
                    usage=None,
                ),
            ]
        )

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.requests.append(dict(kwargs))
        return next(self.responses)


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


@patch.dict("os.environ", {"MIMO_API_KEY": "placeholder-for-tests"}, clear=True)
class MimoRunnerContractTests(unittest.TestCase):
    def test_provider_converts_complete_tool_round_trip(self) -> None:
        provider = MimoProvider(
            api_key="test", base_url="https://example.test/v1", model="mimo"
        )
        completions = FakeCompletions()
        provider.client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        executor = FakeExecutor()
        context = ToolContext(run_id="run-1")
        registry = ToolRegister()
        registry.register(
            tool_from_pydantic(
                name="lookup",
                description="Look up a value",
                args_model=LookupArgs,
                handler=lookup,
            )
        )

        result = AgentRunner(provider, registry, executor).run(
            "find x", context=context
        )

        self.assertEqual((result.output, result.steps), ("42", 2))
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(executor.calls[0][0].arguments, {"key": "x"})
        self.assertIs(executor.calls[0][1], context)
        self.assertEqual(
            completions.requests[0]["tools"][0]["function"]["name"], "lookup"
        )
        follow_up = completions.requests[1]["messages"]
        self.assertEqual(follow_up[1]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(
            json.loads(follow_up[1]["tool_calls"][0]["function"]["arguments"]),
            {"key": "x"},
        )
        self.assertEqual(follow_up[2]["tool_call_id"], "call-1")
        self.assertEqual(
            json.loads(follow_up[2]["content"]),
            {"output": {"value": 42}, "is_error": False},
        )


if __name__ == "__main__":
    unittest.main()
