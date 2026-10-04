"""事件分发与失败隔离。

运行时通过 ``publish`` 发事件，观察者的异常在这里被隔离并记录，绝不传播回
运行时；否则一个错误的订阅者就会改变 Run 的结果。失败处理策略见
``docs/decisions/0003-runtime-event-contract.md``。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .base import EventDeliveryFailure, EventSink, RunEvent

E = TypeVar("E", bound=RunEvent)


def publish(sink: EventSink | None, event: RunEvent) -> None:
    """把事件交给接收端；没有接收端或接收端失败时都不影响运行。"""
    if sink is None:
        return
    try:
        sink.notify(event)
    except Exception as error:  # noqa: BLE001 - 观察者异常必须隔离，不能改变运行结果
        _record_failure(sink, event, error)


def _record_failure(sink: EventSink, event: RunEvent, error: BaseException) -> None:
    """在接收端支持时记录投递失败；记录本身失败也不再抛出。"""
    failures = getattr(sink, "failures", None)
    if failures is None:
        return
    try:
        failures.append(
            EventDeliveryFailure(
                event_type=event.event_type,
                sequence=event.sequence,
                error_type=type(error).__name__,
                message=str(error),
            )
        )
    except Exception:  # noqa: BLE001 - 丢失一条失败记录不应中断运行
        pass


class EventBus:
    """按事件类型分发事件的最小事件总线。

    订阅一个基类即可收到它的所有子类事件，例如订阅 ``RunEvent`` 会收到全部
    运行时事件。处理器按注册顺序同步调用，因此事件顺序与运行时状态一致。
    """

    def __init__(self) -> None:
        #: 被隔离的投递失败，供外层排查订阅者问题。
        self.failures: list[EventDeliveryFailure] = []
        self._handlers: list[tuple[type[RunEvent], Callable[[RunEvent], None]]] = []
        self._cache: dict[type[RunEvent], tuple[Callable[[RunEvent], None], ...]] = {}

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> Callable[[], None]:
        """注册处理器并返回取消订阅的函数。"""
        self._handlers.append((event_type, handler))
        self._cache.clear()

        def unsubscribe() -> None:
            self.unsubscribe(event_type, handler)

        return unsubscribe

    def unsubscribe(
        self,
        event_type: type[RunEvent],
        handler: Callable[..., None],
    ) -> None:
        """移除已注册的处理器；未注册时不做任何事。"""
        for index, (subscribed_type, subscribed_handler) in enumerate(self._handlers):
            if subscribed_type is event_type and subscribed_handler is handler:
                del self._handlers[index]
                self._cache.clear()
                return

    def on(
        self, event_type: type[E]
    ) -> Callable[[Callable[[E], None]], Callable[[E], None]]:
        """订阅装饰器：``@bus.on(StepEnd)``。"""

        def decorator(handler: Callable[[E], None]) -> Callable[[E], None]:
            self.subscribe(event_type, handler)
            return handler

        return decorator

    def clear(self) -> None:
        """移除全部订阅，保留失败记录。"""
        self._handlers.clear()
        self._cache.clear()

    def notify(self, event: RunEvent) -> None:
        """分发给匹配的处理器；单个处理器失败不影响其他处理器。"""
        for handler in self._matching(type(event)):
            try:
                handler(event)
            except Exception as error:  # noqa: BLE001 - 隔离订阅者异常
                self.failures.append(
                    EventDeliveryFailure(
                        event_type=event.event_type,
                        sequence=event.sequence,
                        error_type=type(error).__name__,
                        message=str(error),
                    )
                )

    def _matching(
        self, event_class: type[RunEvent]
    ) -> tuple[Callable[[RunEvent], None], ...]:
        """按事件实际类型缓存匹配结果，避免每次分发重复判断继承关系。"""
        matched = self._cache.get(event_class)
        if matched is None:
            matched = tuple(
                handler
                for subscribed_type, handler in self._handlers
                if issubclass(event_class, subscribed_type)
            )
            self._cache[event_class] = matched
        return matched
