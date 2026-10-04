"""事件显式导出字段；未知字段不会随反射自动跨过应用边界。"""

from dataclasses import asdict, dataclass
from enum import Enum
from json import dumps, loads

from slothy.core.events.base import ErrorInfo, RunEvent
from slothy.core.model import ModelUsage


_PAYLOAD_FIELDS = {
    "run.started": ("max_steps", "deadline_seconds"),
    "run.completed": ("steps", "duration_ms"),
    "run.failed": ("steps", "duration_ms", "error"),
    "run.cancelled": ("steps", "duration_ms"),
    "run.suspended": ("reason",),
    "run.resumed": ("generation",),
    "run.step.started": (),
    "run.step.ended": ("outcome", "duration_ms", "tool_call_count"),
    "run.step.timeout": ("duration_ms", "timeout_seconds"),
    "run.step.limit": ("max_steps", "requested_tool_calls"),
    "run.model.request_started": ("message_count", "tool_count"),
    "run.model.responded": ("duration_ms", "text_length", "tool_call_count", "usage"),
    "run.model.token_chunk": ("index", "text", "role"),
    "run.model.error": ("duration_ms", "error"),
    "run.model.timeout": ("duration_ms", "error"),
    "run.tool.call_started": ("call_id", "name", "argument_keys"),
    "run.tool.call_ended": ("call_id", "name", "duration_ms", "is_error", "output_size"),
    "run.tool.progress": ("call_id", "name", "completed", "total", "message"),
    "run.tool.timeout": ("call_id", "name", "duration_ms", "error"),
    "run.tool.error": ("call_id", "name", "duration_ms", "error"),
    "run.tool.approval_requested": ("call_id", "request_id", "name", "attempt", "reason"),
    "run.tool.approval_resolved": ("call_id", "request_id", "name", "approved"),
    "run.context.compressed": (
        "tokens_before", "tokens_after", "messages_removed", "messages_truncated", "strategy",
    ),
    "run.policy.triggered": ("policy", "decision", "reason"),
    "run.policy.guardrail_blocked": ("guardrail", "call_id", "name", "reason"),
    "run.observability.token_usage": ("usage", "cumulative"),
    "run.observability.metric": ("name", "value", "unit"),
}


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (ErrorInfo, ModelUsage)):
        return asdict(value)
    return value


@dataclass(frozen=True)
class EventDTO:
    cursor: int
    event_type: str
    run_id: str
    sequence: int
    step_number: int | None
    occurred_at: float
    status: str
    generation: int
    payload: dict

    @classmethod
    def from_event(cls, event: RunEvent, cursor: int, *, status: str, generation: int):
        payload = {
            name: _json_value(getattr(event, name))
            for name in _PAYLOAD_FIELDS[event.event_type]
        }
        payload = loads(dumps(payload, ensure_ascii=False, allow_nan=False))
        return cls(
            cursor, event.event_type, event.run_id, event.sequence,
            event.step_number, event.occurred_at, status, generation, payload,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EventPageDTO:
    events: list[EventDTO]
    next_cursor: int
    oldest_cursor: int
    truncated: bool
    has_more: bool

    def to_dict(self) -> dict:
        return asdict(self)
