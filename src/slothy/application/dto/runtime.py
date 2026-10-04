"""Presentation 可见的数据副本；不传递 Run、处理函数或原始快照。"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorDTO:
    code: str
    message: str
    run_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StepDTO:
    number: int
    status: str
    call_ids: list[str]
    duration_ms: float


@dataclass(frozen=True)
class RunDTO:
    run_id: str
    status: str
    busy: bool
    max_steps: int
    step_count: int
    steps: list[StepDTO]
    duration_ms: float
    generation: int
    snapshot_revision: int | None
    output: str | None
    error_code: str | None
    approval_request_id: str | None
    approval_decision: str | None
    cancel_requested: bool
    interrupt_requested: bool
    event_cursor: int
    observer_failure_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDTO:
    request_id: str
    run_id: str
    step_number: int
    call_id: str
    tool_name: str
    fingerprint: str
    attempt: int
    reason: str
    arguments: dict[str, Any]
    snapshot_revision: int
    decision: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDecisionDTO:
    request_id: str
    approved: bool
    actor_id: str
    snapshot_revision: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolDTO:
    name: str
    description: str
    parameters: dict[str, Any]
    replay_safety: str
    execution_version: str | None
    timeout_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
