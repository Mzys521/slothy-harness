"""按到达顺序记录运行时事件的时间线。

``RunTimeline`` 是 ``EventSink`` 的一个最小实现：它只按顺序保存事件，供测试
断言顺序和外层（界面、日志、后续持久化）读取。它不是第二个事件总线，不做
过滤之外的任何决策。
"""

from __future__ import annotations

from typing import TypeVar, overload

from .base import EventDeliveryFailure, RunEvent
from .dispatch import EventBus

E = TypeVar("E", bound=RunEvent)


class RunTimeline:
    """订阅全部运行时事件并保存为有序时间线。

    时间线是观察者，不改变运行时行为：投递失败的异常由事件总线隔离并记录在
    ``failures`` 中，与总线共享同一份失败记录。
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        """订阅给定事件总线；不传时由调用方用 ``notify`` 手动送入事件。"""
        self._events: list[RunEvent] = []
        self.failures: list[EventDeliveryFailure] = (
            bus.failures if bus is not None else []
        )
        if bus is not None:
            bus.subscribe(RunEvent, self.notify)

    @property
    def events(self) -> tuple[RunEvent, ...]:
        """按到达顺序返回已记录的事件。"""
        return tuple(self._events)

    def notify(self, event: RunEvent) -> None:
        """记录一个事件。"""
        self._events.append(event)

    def clear(self) -> None:
        """清空已记录的事件。"""
        self._events.clear()

    def types(self) -> list[str]:
        """返回事件类型标识列表，便于直接断言顺序。"""
        return [event.event_type for event in self._events]

    @overload
    def of_type(self, event_type: type[E]) -> tuple[E, ...]: ...

    @overload
    def of_type(self, event_type: str) -> tuple[RunEvent, ...]: ...

    def of_type(self, event_type: type[E] | str) -> tuple[RunEvent, ...]:
        """返回指定类型或类型标识的事件元组。"""
        if isinstance(event_type, str):
            return tuple(
                event for event in self._events if event.event_type == event_type
            )
        return tuple(event for event in self._events if isinstance(event, event_type))

    @overload
    def first(self, event_type: type[E]) -> E | None: ...

    @overload
    def first(self, event_type: str) -> RunEvent | None: ...

    def first(self, event_type: type[E] | str) -> RunEvent | None:
        """返回第一个指定类型的事件；没有时返回 ``None``。"""
        matched = self.of_type(event_type)  # type: ignore[arg-type]
        return matched[0] if matched else None

    def describe(self) -> str:
        """返回便于测试失败时阅读的事件顺序摘要。"""
        return " → ".join(self.types())
