"""Run 的事件绑定与步骤/运行耗时，独立于循环的领域模块。"""

from slothy.core.events import EventSink, Metric
from slothy.core.events.emitter import EventEmitter

from .state import RUN_TERMINAL_STATUSES, Run

RUN_DURATION_METRIC = "run.duration_ms"
STEP_DURATION_METRIC = "step.duration_ms"


class RunObservation:
    """在启动前绑定中继，为各模块共享事件序列并记录运行指标。"""

    def __init__(self, state: Run, events: EventSink | None = None) -> None:
        self._state = state
        relay = state.create_relay(events if events is not None else state.events)
        self.events = EventEmitter(
            lambda event: relay.emit(state, event), enabled=relay.sink is not None
        )
        self._run_duration_ms: float | None = None

    def step_finished(self) -> None:
        step = self._state.current_step
        if step is not None:
            self.events.emit(
                Metric(name=STEP_DURATION_METRIC, value=step.duration_ms, unit="ms")
            )

    def run_finished(self) -> None:
        """只在终态发出一次整次执行的耗时。"""
        if self._run_duration_ms is not None:
            return
        if self._state.status not in RUN_TERMINAL_STATUSES:
            return
        self._run_duration_ms = self._state.duration_ms
        self.events.emit(
            Metric(name=RUN_DURATION_METRIC, value=self._run_duration_ms, unit="ms")
        )
