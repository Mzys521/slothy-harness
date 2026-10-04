"""核心事件契约。

运行时在已有状态转换处发出提供方无关的事件；界面、日志和持久化通过
``EventSink`` 协议接收事件，相关实现位于外层，核心层不得导入它们。

事件分为五类：

- 生命周期：``RunStarted``、``RunCompleted``、``RunFailed``、``RunCancelled``、
  ``StepStarted``、``StepEnd``、``StepTimeout``、``StepLimitReached``、
  ``RunSuspended``、``RunResumed``
- 模型：``ModelRequestStart``、``ModelResponded``、``TokenChunk``、
  ``ModelError``、``LLMTimeout``
- 工具：``ToolCallStart``、``ToolCallEnd``、``ToolProgress``、``ToolTimeout``、
  ``ToolError``
- 状态与策略：``ContextCompressed``、``PolicyTriggered``、``GuardrailBlocked``、
  ``ToolApprovalRequested``、``ToolApprovalResolved``
- 观测：``TokenUsage``、``Metric``

用法与事件顺序见 ``docs/runtime-events.md``。
"""

from .base import (
    EventDeliveryFailure,
    EventSink,
    ErrorInfo,
    RunCheckedError,
    RunEvent,
    describe_error,
)
from .dispatch import EventBus, publish
from .lifecycle import (
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunLifecycleEvent,
    RunStarted,
    StepEnd,
    StepEvent,
    StepLimitReached,
    StepOutcome,
    StepStarted,
    StepTimeout,
)
from .model import (
    LLMTimeout,
    LLMTimeoutError,
    ModelCheckedError,
    ModelError,
    ModelEvent,
    ModelRequestStart,
    ModelResponded,
    TokenChunk,
    TransientModelError,
)
from .observability import Metric, TokenUsage
from .status import ContextCompressed, GuardrailBlocked, PolicyTriggered
from .tool import (
    ToolCallEnd,
    ToolCallStart,
    ToolCheckedError,
    ToolError,
    ToolEvent,
    ToolProgress,
    ToolTimeout,
    ToolTimeoutError,
)
from .tracing import RunTimeline
from .recovery import (
    RunResumed, RunSuspended, ToolApprovalRequested, ToolApprovalResolved,
)

LIFECYCLE_EVENTS: tuple[type[RunEvent], ...] = (
    RunStarted,
    RunCompleted,
    RunFailed,
    RunCancelled,
    StepStarted,
    StepEnd,
    StepTimeout,
    StepLimitReached,
    RunSuspended,
    RunResumed,
)
MODEL_EVENTS: tuple[type[RunEvent], ...] = (
    ModelRequestStart,
    ModelResponded,
    TokenChunk,
    ModelError,
    LLMTimeout,
)
TOOL_EVENTS: tuple[type[RunEvent], ...] = (
    ToolCallStart,
    ToolCallEnd,
    ToolProgress,
    ToolTimeout,
    ToolError,
)
STATUS_EVENTS: tuple[type[RunEvent], ...] = (
    ContextCompressed,
    PolicyTriggered,
    GuardrailBlocked,
    ToolApprovalRequested,
    ToolApprovalResolved,
)
OBSERVABILITY_EVENTS: tuple[type[RunEvent], ...] = (TokenUsage, Metric)

#: 全部已定义事件，供日志、界面和测试遍历分类表。
EVENT_TYPES: tuple[type[RunEvent], ...] = (
    *LIFECYCLE_EVENTS,
    *MODEL_EVENTS,
    *TOOL_EVENTS,
    *STATUS_EVENTS,
    *OBSERVABILITY_EVENTS,
)

__all__ = [
    "RunResumed", "RunSuspended", "ToolApprovalRequested", "ToolApprovalResolved",
    "TransientModelError",
    "ContextCompressed",
    "EVENT_TYPES",
    "EventBus",
    "EventDeliveryFailure",
    "EventSink",
    "ErrorInfo",
    "GuardrailBlocked",
    "LIFECYCLE_EVENTS",
    "LLMTimeout",
    "LLMTimeoutError",
    "MODEL_EVENTS",
    "Metric",
    "ModelCheckedError",
    "ModelError",
    "ModelEvent",
    "ModelRequestStart",
    "ModelResponded",
    "OBSERVABILITY_EVENTS",
    "PolicyTriggered",
    "RunCancelled",
    "RunCheckedError",
    "RunCompleted",
    "RunEvent",
    "RunFailed",
    "RunLifecycleEvent",
    "RunStarted",
    "RunTimeline",
    "STATUS_EVENTS",
    "StepEnd",
    "StepEvent",
    "StepLimitReached",
    "StepOutcome",
    "StepStarted",
    "StepTimeout",
    "TOOL_EVENTS",
    "TokenChunk",
    "TokenUsage",
    "ToolCallEnd",
    "ToolCallStart",
    "ToolCheckedError",
    "ToolError",
    "ToolEvent",
    "ToolProgress",
    "ToolTimeout",
    "ToolTimeoutError",
    "describe_error",
    "publish",
]
