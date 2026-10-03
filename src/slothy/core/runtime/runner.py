"""智能体循环，协调模型响应与受控的工具执行。"""

from typing import Any

from slothy.core.model import ModelProvider
from slothy.core.tools import ToolContext, ToolExecutor, ToolRegistry
from .state import Run, RunCancelledError

from .runner_models import RunnerResult


class AgentRunner:
    def __init__(
        self,
        model: ModelProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model = model
        self.registry = registry
        self.executor = executor
        self.max_steps = max_steps

    def run(
        self,
        user_input: str,
        *,
        context: ToolContext,
        runtime: Run | None = None,
    ) -> RunnerResult:
        """运行直到模型给出回答或达到模型调用次数上限。

        注入的执行器负责校验与权限决策。运行器只将请求的调用传递给它，
        并在下一轮对话中将结果返回给模型。
        """
        state = runtime or Run(run_id=context.run_id, max_steps=self.max_steps)
        if state.run_id != context.run_id or state.max_steps != self.max_steps:
            raise ValueError("运行时状态与当前执行上下文不匹配")
        state.start()

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_input}]

        try:
            tools = self.registry.definitions()
            for step in range(1, self.max_steps + 1):
                state.begin_step(step)
                response = self.model.generate(messages, tools=tools)
                state.check_active()
                if not response.tool_calls:
                    state.finish_step()
                    state.complete()
                    return RunnerResult(output=response.text or "", steps=step, run=state)

                if step == self.max_steps:
                    raise RuntimeError(f"Exceeded max steps ({self.max_steps})")

                state.wait_for_tool()
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.text or "",
                        "tool_calls": [
                            {
                                "call_id": call.call_id,
                                "name": call.name,
                                "arguments": call.arguments,
                            }
                            for call in response.tool_calls
                        ],
                    }
                )

                for call in response.tool_calls:
                    state.begin_tool_call(call.call_id)
                    tool_result = self.executor.execute(call, context)
                    state.check_active()
                    messages.append(
                        {
                            "role": "tool",
                            "call_id": call.call_id,
                            "content": tool_result.to_model_output(),
                        }
                    )
                    state.wait_for_tool()
                state.finish_step()

            raise AssertionError("The step loop must return or raise")
        except RunCancelledError:
            raise
        except Exception:
            state.fail()
            raise
