"""工具重放安全契约；这些字段只由可信注册方与宿主设置。"""

from dataclasses import dataclass, field
from copy import deepcopy
from enum import Enum
from hashlib import sha256
from json import dumps
from typing import Protocol

from slothy.core.model.model_models import ToolCall
from slothy.core.events.base import RunCheckedError

from .tool_models import ToolContext, ToolResult


class ReplaySafety(str, Enum):
    UNSPECIFIED = "unspecified"
    IDEMPOTENT = "idempotent"
    KEYED = "keyed"
    UNVERIFIABLE = "unverifiable"


class VerificationStatus(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class IdempotencyConflictError(RunCheckedError):
    error_code = "idempotency_conflict"


class IdempotencyUncertainError(RunCheckedError):
    error_code = "tool_execution_unknown"


@dataclass(frozen=True)
class IdempotencyCheck:
    status: VerificationStatus
    result: ToolResult | None = None

    def __post_init__(self):
        if not isinstance(self.status, VerificationStatus):
            raise ValueError("invalid verification status")
        if (self.status is VerificationStatus.COMPLETED) != (self.result is not None):
            raise ValueError("only completed verification has a result")
        if self.result is not None and not isinstance(self.result, ToolResult):
            raise ValueError("completed verification requires a ToolResult")


class IdempotencyVerifier(Protocol):
    def verify_idempotency(
        self, call: ToolCall, context: ToolContext,
    ) -> IdempotencyCheck:
        """校验宿主提供的键与指纹；UNKNOWN 禁止静默重放。"""
        ...


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    run_id: str
    step_number: int
    call_id: str
    tool_name: str
    fingerprint: str
    attempt: int
    reason: str
    arguments: dict = field(default_factory=dict)

    def __post_init__(self):
        if any(not isinstance(value, str) or not value for value in (
            self.request_id, self.run_id, self.call_id, self.tool_name,
            self.fingerprint, self.reason,
        )) or any(isinstance(value, bool) or not isinstance(value, int) or value < 1
                  for value in (self.step_number, self.attempt)):
            raise ValueError("invalid approval request")
        if not isinstance(self.arguments, dict):
            raise ValueError("invalid approval arguments")
        dumps(self.arguments, allow_nan=False)
        object.__setattr__(self, "arguments", deepcopy(self.arguments))


@dataclass(frozen=True)
class ApprovalDecision:
    """只能由受信任的宿主在人确认之后提交；模型参数不能产生此对象。"""

    request_id: str
    approved: bool
    actor: str

    def __post_init__(self):
        if (
            not isinstance(self.approved, bool)
            or not isinstance(self.request_id, str) or not self.request_id
            or not isinstance(self.actor, str) or not self.actor.strip()
        ):
            raise ValueError("approval requires request_id, bool and actor")


def request_fingerprint(call: ToolCall, version: str) -> str:
    prepared = dumps(
        [call.name, version, call.arguments], ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return sha256(prepared.encode("utf-8")).hexdigest()


def idempotency_key(run_id: str, step: int, call_id: str, fingerprint: str) -> str:
    prepared = dumps([run_id, step, call_id, fingerprint], ensure_ascii=False)
    return "slothy:" + sha256(prepared.encode("utf-8")).hexdigest()
