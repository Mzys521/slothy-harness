"""恢复与审批事件，只携带标识和安全分类。"""

from dataclasses import dataclass

from .lifecycle import RunLifecycleEvent
from .tool import ToolEvent


@dataclass
class RunSuspended(RunLifecycleEvent):
    EVENT_TYPE = "run.suspended"
    reason: str = "interrupted"


@dataclass
class RunResumed(RunLifecycleEvent):
    EVENT_TYPE = "run.resumed"
    generation: int = 1


@dataclass
class ToolApprovalRequested(ToolEvent):
    EVENT_TYPE = "run.tool.approval_requested"
    request_id: str = ""
    name: str = ""
    attempt: int = 1
    reason: str = "unverifiable"


@dataclass
class ToolApprovalResolved(ToolEvent):
    EVENT_TYPE = "run.tool.approval_resolved"
    request_id: str = ""
    name: str = ""
    approved: bool = False
