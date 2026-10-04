"""模块共享的事件发射入口，不包含模型、工具或运行状态逻辑。"""

from collections.abc import Callable
from time import monotonic

from slothy.core.timing import elapsed_ms

from .base import RunEvent


class EventEmitter:
    """把模块事件交给已绑定 Run 的中继，并统一计算边界耗时。"""

    def __init__(
        self, deliver: Callable[[RunEvent], None], *, enabled: bool
    ) -> None:
        self._deliver = deliver
        self.enabled = enabled

    def emit(self, event: RunEvent) -> None:
        self._deliver(event)

    def clock(self) -> float:
        return monotonic()

    def elapsed(self, started_at: float) -> float:
        return elapsed_ms(started_at, self.clock())
