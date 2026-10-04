"""应用层事件接收、有限缓存和 DTO 推送；监听失败不影响执行。"""

from collections import deque
from collections.abc import Callable
from threading import RLock
from uuid import uuid4

from slothy.application.dto import EventDTO, EventPageDTO
from slothy.application.errors import ApplicationError
from slothy.core.events import RunEvent


class RuntimeObservation:
    def __init__(self, before_event: Callable, *, capacity: int):
        self._before_event = before_event
        self._events: deque[EventDTO] = deque(maxlen=capacity)
        self._listeners: dict[str, Callable[[dict], None]] = {}
        self._lock = RLock()
        self.cursor = 0
        self.failure_count = 0

    def notify(self, event: RunEvent) -> None:
        try:
            status, generation = self._before_event(event)
            with self._lock:
                record = EventDTO.from_event(
                    event, self.cursor + 1, status=status, generation=generation,
                )
                self.cursor = record.cursor
                self._events.append(record)
                listeners = tuple(self._listeners.values())
        except Exception:
            with self._lock:
                self.failure_count += 1
            return
        for listener in listeners:
            try:
                listener(record.to_dict())
            except Exception:
                with self._lock:
                    self.failure_count += 1

    def subscribe(self, listener: Callable[[dict], None]) -> str:
        if not callable(listener):
            raise ApplicationError("invalid_request", "事件监听器必须为宿主提供的回调。")
        subscription_id = uuid4().hex
        with self._lock:
            self._listeners[subscription_id] = listener
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            return self._listeners.pop(subscription_id, None) is not None

    def page(self, *, after: int, limit: int) -> EventPageDTO:
        with self._lock:
            if after > self.cursor:
                raise ApplicationError("invalid_request", "事件游标超过当前缓存范围。")
            oldest = self._events[0].cursor if self._events else self.cursor + 1
            records = [event for event in self._events if event.cursor > after][:limit]
            next_cursor = records[-1].cursor if records else after
            return EventPageDTO(
                records, next_cursor, oldest, after < oldest - 1, next_cursor < self.cursor,
            )
