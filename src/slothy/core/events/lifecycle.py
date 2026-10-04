"""Run 与 Step 的生命周期事件。

这些事件由 ``Run`` 的状态转换直接发出，因此事件顺序与运行时状态始终一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .base import ErrorInfo, RunEvent


class StepOutcome(str, Enum):
    """一次步骤的终态，用于区分正常结束与被终止。"""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunLifecycleEvent(RunEvent):
    """描述整次执行走向终态的事件。"""

    EVENT_TYPE = "run.lifecycle"


@dataclass
class StepEvent(RunEvent):
    """描述单个模型步骤的事件。"""

    EVENT_TYPE = "run.step"


@dataclass
class RunStarted(RunLifecycleEvent):
    """执行开始，后续所有事件都属于同一次 Run。"""

    EVENT_TYPE = "run.started"

    max_steps: int = 0
    deadline_seconds: float | None = None


@dataclass
class RunCompleted(RunLifecycleEvent):
    """执行成功结束：

    最后一次模型调用没有请求工具并给出了回答。
    """

    EVENT_TYPE = "run.completed"

    steps: int = 0
    duration_ms: float = 0.0


@dataclass
class RunFailed(RunLifecycleEvent):
    """执行失败结束，是失败 Run 的唯一终态事件。"""

    EVENT_TYPE = "run.failed"

    steps: int = 0
    duration_ms: float = 0.0
    error: ErrorInfo | None = None


@dataclass
class RunCancelled(RunLifecycleEvent):
    """执行被协作式取消，是取消 Run 的唯一终态事件。"""

    EVENT_TYPE = "run.cancelled"

    steps: int = 0
    duration_ms: float = 0.0


@dataclass
class StepStarted(StepEvent):
    """一个模型步骤开始，准备发起模型调用。"""

    EVENT_TYPE = "run.step.started"


@dataclass
class StepEnd(StepEvent):
    """一个步骤到达终态，正常情况下每个步骤只出现一次。

    超时和失败原因由 ``StepTimeout``、``RunFailed``、``RunCancelled`` 等
    事件说明，本事件只给出终态本身。
    """

    EVENT_TYPE = "run.step.ended"

    outcome: StepOutcome = StepOutcome.COMPLETED
    duration_ms: float = 0.0
    tool_call_count: int = 0


@dataclass
class StepTimeout(StepEvent):
    """步骤执行时间超过 ``Run.step_timeout_seconds``，紧随其后是失败终态。"""

    EVENT_TYPE = "run.step.timeout"

    duration_ms: float = 0.0
    timeout_seconds: float = 0.0


@dataclass
class StepLimitReached(StepEvent):
    """最后一步仍在请求工具，运行器拒绝执行无法反馈给模型的工具调用。"""

    EVENT_TYPE = "run.step.limit"

    max_steps: int = 0
    requested_tool_calls: int = 0
