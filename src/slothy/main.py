"""计算工具 Agent 的命令行入口与依赖组装。"""

from uuid import uuid4

from dotenv import load_dotenv

from slothy.core.model import ModelProvider
from slothy.core.runtime import AgentRunner, RunnerResult
from slothy.core.tools import ToolContext, ToolRegistry
from slothy.infrastructure.app_tools import CalculatorToolExecutor, tool_list
from slothy.infrastructure.llm.providers.mimo_provider import MimoProvider

def run_calculation(
    user_input: str, *, model: ModelProvider | None = None
) -> RunnerResult:
    """组装计算工具，运行一次完整的 Agent 循环。"""
    if model is None:
        load_dotenv()
        model = MimoProvider()

    registry = ToolRegistry()
    for tool in tool_list:
        registry.register(tool)

    runner = AgentRunner(
        model=model,
        registry=registry,
        executor=CalculatorToolExecutor(registry),
    )

    return runner.run(user_input, context=ToolContext(run_id=uuid4().hex))


if __name__ == "__main__":
    user_input = "现在需要你为我计算 2 + 3^4 / 15 和 16 * 4 - 2 结果的乘积"
    result = run_calculation(user_input)
    print(result.output)
