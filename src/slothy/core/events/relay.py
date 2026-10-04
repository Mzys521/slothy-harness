"""事件中继：为事件补充运行上下文和序列号。

一次 Run 的所有事件必须共享同一个序列号空间，无论它来自 ``Run`` 的状态迁移
还是领域模块的模型、工具边界。因此 ``Run`` 持有一个中继，各模块经统一的
事件发射入口复用它，而不是各自计数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import EventSink, RunEvent
from .dispatch import publish

if TYPE_CHECKING:
    from slothy.core.runtime.state import Run


class EventRelay:
    """补充 ``run_id``、``step_number`` 与 ``sequence`` 并安全分发事件。"""

    def __init__(self, sink: EventSink | None = None) -> None:
        self.sink = sink
        self.sequence = 0

    def emit(self, run: Run, event: RunEvent) -> None:
        """补充上下文后分发；接收端缺失或失败都不影响运行。"""
        self.sequence += 1
        event.run_id = run.run_id
        event.sequence = self.sequence
        step = run.current_step
        event.step_number = step.number if step is not None else None
        publish(self.sink, event)
