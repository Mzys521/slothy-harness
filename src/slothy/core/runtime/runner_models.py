"""智能体运行器返回的结果。"""

from dataclasses import dataclass

from .state import Run


@dataclass(frozen=True)
class RunnerResult:
    output: str
    steps: int
    run: Run | None = None
