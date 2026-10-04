"""智能体运行器返回的结果。"""

from dataclasses import dataclass

from .state import Run
from .snapshot import RuntimeSnapshot
from slothy.core.tools.replay import ApprovalRequest


@dataclass(frozen=True)
class RunnerResult:
    output: str
    steps: int
    run: Run | None = None
    snapshot: RuntimeSnapshot | None = None
    approval: ApprovalRequest | None = None
