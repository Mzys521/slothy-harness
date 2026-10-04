"""端到端演示：策略拦截、进度上报与上下文压缩在一次运行中同时出现。"""

from typing import Any

from slothy.core.context import ContextWindow
from slothy.core.events import RunTimeline
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import PolicyEngine, PolicyVerdict, ToolNameRule
from slothy.core.runtime import AgentRunner
from slothy.core.tools import ProgressCallback, ProgressReport, ToolContext, ToolResult


class DemoModel(ModelProvider):
    def __init__(self) -> None:
        self.rounds = 0

    def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> ModelResult:
        on_chunk = kwargs.get("on_chunk")
        self.rounds += 1
        if self.rounds == 1:
            return ModelResult(
                tool_calls=[
                    ToolCall("call-1", "slow_report", {"topic": "年报"}),
                    ToolCall("call-2", "shell_exec", {"command": "rm -rf /"}),
                ]
            )
        if on_chunk is not None:
            on_chunk("已")
            on_chunk("完成")
        return ModelResult(text="已完成分析")


class DemoExecutor:
    def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        on_progress: ProgressCallback | None = None,
    ) -> ToolResult:
        for index in (1, 2):
            if on_progress is not None:
                on_progress(ProgressReport(completed=index, total=2, message="分析中"))
        return ToolResult(output={"rows": 128})


class DemoRegistry:
    def definitions(self) -> list[dict[str, Any]]:
        return [
            {"name": "slow_report", "description": "生成慢报表"},
            {"name": "shell_exec", "description": "执行命令"},
        ]


window = ContextWindow(token_budget=60)
window.add({"role": "user", "content": "历史问题一：" + "细节" * 40})
window.add({"role": "assistant", "content": "历史回答一：" + "细节" * 40})

timeline = RunTimeline()
runner = AgentRunner(
    DemoModel(),
    DemoRegistry(),
    DemoExecutor(),
    max_steps=4,
    policy=PolicyEngine(
        rules=(ToolNameRule("shell*", PolicyVerdict.DENY, reason="禁止命令行"),)
    ),
    context=window,
)
result = runner.run("请汇总年报", context=ToolContext(run_id="demo-run"), events=timeline)

print("最终输出：", result.output)
print("事件顺序：")
for event in timeline.events:
    print(f"  {event.sequence:>2}  {event.event_type}")
