"""同一 Runner 注入 5 轮、20 轮 / 30s、重试、安全策略；无网络、无等待。"""

from contextlib import ExitStack
from unittest.mock import patch

from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import DefaultPolicy, RetryPolicy, SafetyPolicy, TimeoutPolicy
from slothy.core.runtime import AgentRunner, RunStateError
from slothy.core.tools import ToolContext, ToolResult


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Model(ModelProvider):
    def __init__(self, clock, seconds=0, failures=0):
        self.clock = clock
        self.seconds = seconds
        self.failures = failures
        self.requests = 0

    def generate(self, messages, **kwargs):
        self.requests += 1
        self.clock.now += self.seconds
        if self.requests <= self.failures:
            raise ConnectionError("temporary failure")
        if self.failures:
            return ModelResult(text="recovered")
        return ModelResult(tool_calls=[ToolCall(
            f"call-{self.requests}", "lookup", {"key": "x"},
        )])


class Registry:
    def definitions(self):
        return [{"name": "lookup"}]


class Executor:
    def __init__(self):
        self.calls = 0

    def execute(self, call, context, on_progress=None):
        self.calls += 1
        return ToolResult(output=42)


def demonstrate(label, policy, seconds=0, failures=0):
    clock = Clock()
    model, executor = Model(clock, seconds, failures), Executor()
    runner = AgentRunner(model, Registry(), executor, policy=policy)
    with ExitStack() as patches:
        for target in (
            "slothy.core.runtime.state.monotonic",
            "slothy.core.events.emitter.monotonic",
            "slothy.core.timing.monotonic",
        ):
            patches.enter_context(patch(target, clock))
        try:
            result = runner.run("test", context=ToolContext(label))
            outcome = result.output
        except RunStateError as error:
            outcome = error.error_code
    print(f"{label}: models={model.requests}, tools={executor.calls}, "
          f"elapsed={clock.now:g}s, outcome={outcome}")
    return model.requests, executor.calls, clock.now, outcome


if __name__ == "__main__":
    assert demonstrate("five-rounds", DefaultPolicy(5)) == (
        5, 4, 0, "step_limit_reached",
    )
    assert demonstrate(
        "twenty-rounds-thirty-seconds",
        TimeoutPolicy(DefaultPolicy(20), timeout_seconds=30), seconds=10,
    ) == (3, 2, 30, "run_timeout")
    assert demonstrate("retry", RetryPolicy(), failures=2) == (
        3, 0, 0, "recovered",
    )
    assert demonstrate("no-progress", SafetyPolicy(no_progress_limit=3)) == (
        3, 3, 0, "no_progress",
    )
