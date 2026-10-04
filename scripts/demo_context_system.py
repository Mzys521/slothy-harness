"""无网络长任务：使用同一个 Runner 验证截断和注入摘要策略的 8k 窗口。"""

from copy import deepcopy

from slothy.core.context import InMemoryContext, SummaryStrategy, TrimOldestStrategy
from slothy.core.events import ContextCompressed, RunTimeline
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.runtime import AgentRunner
from slothy.core.tools import ToolContext, ToolResult


class DemoRegistry:
    def definitions(self):
        return [{"name": "read_batch", "description": "Read the next batch"}]


class DemoModel(ModelProvider):
    def __init__(self, context):
        self.context = context
        self.requests = []

    def generate(self, messages, **kwargs):
        tokens = self.context.estimator.estimate(messages)
        assert tokens <= 8192, f"Request exceeds budget: {tokens}"
        self.requests.append(deepcopy(messages))
        if len(self.requests) <= 16:
            return ModelResult(tool_calls=[
                ToolCall(f"batch-{len(self.requests)}", "read_batch", {})
            ])
        return ModelResult(text="Long task completed")


class DemoExecutor:
    def execute(self, call, context, on_progress=None):
        repeats = 12000 if call.call_id == "batch-1" else 700
        return ToolResult(output={
            "batch": call.call_id, "data": "工具数据" * repeats
        })


def demo(strategy, label):
    context = InMemoryContext(
        system_prompt="Complete the long task.", strategy=strategy
    )
    model = DemoModel(context)
    timeline = RunTimeline()
    result = AgentRunner(
        model, DemoRegistry(), DemoExecutor(), context=context, max_steps=17
    ).run("Analyse all batches", context=ToolContext(f"long-{label}"), events=timeline)
    compressed = timeline.of_type(ContextCompressed)
    history_tokens = context.estimator.estimate(context.get_history())
    maximum = max(
        context.estimator.estimate(messages) for messages in model.requests
    )
    assert history_tokens > 8192
    assert compressed
    print(
        f"{label}: steps={result.steps}, history_tokens={history_tokens}, "
        f"max_request_tokens={maximum}, budget=8192, "
        f"compressions={len(compressed)}, "
        "tool_results_truncated="
        f"{sum(event.messages_truncated for event in compressed)}"
    )
    return compressed


if __name__ == "__main__":
    demo(TrimOldestStrategy(), "trim")
    summary_calls = []

    def fake_summarizer(messages, output_token_budget):
        summary_calls.append(len(messages))
        return (
            "Previous batches have been analysed; continue with the remaining batches."
        )

    events = demo(SummaryStrategy(fake_summarizer), "summary")
    assert any(event.strategy == "summarize" for event in events)
    print(f"summary: summarizer_calls={len(summary_calls)}")
