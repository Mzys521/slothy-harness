"""一次 Agent 执行及其步骤的最小运行时状态。

状态转换是生命周期事件的唯一来源：``Run`` 每次迁移都通过 ``EventSink`` 发出对应事件，
因此事件顺序与运行状态始终一致。观察者的异常由事件总线隔离，不改变运行结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from time import monotonic
from typing import TYPE_CHECKING, Callable

from slothy.core.events import (
    EventSink,
    ErrorInfo,
    PolicyTriggered,
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    RunResumed,
    RunSuspended,
    StepEnd,
    StepLimitReached,
    StepOutcome,
    StepStarted,
    StepTimeout,
    describe_error,
)
from slothy.core.events.relay import EventRelay
from slothy.core.timing import elapsed_ms
from slothy.core.policy import (
    DefaultPolicy, Policy, PolicySnapshot, Termination, TerminationKind,
    TimeoutPolicy,
)

if TYPE_CHECKING:
    from .snapshot import RuntimeSnapshot


class RunStatus(str, Enum):
    """一次执行可观察到的状态。"""

    IDLE = "idle"
    RUNNING = "running"
    THINKING = "thinking"
    WAITING_TOOL = "waiting_tool"
    EXECUTING_TOOL = "executing_tool"
    SUSPENDED = "suspended"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """单个模型步骤的结束状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStateError(RuntimeError):
    """运行时状态异常的基类。

    每个子类都提供稳定的 ``error_code``：事件只携带该分类，不携带原始异常文本，
    因此事件中不会出现本地路径或提供方细节。
    """

    #: 事件的 ``ErrorInfo.error_code``；由子类覆盖。
    error_code = "runtime_error"


class RunCancelledError(RunStateError):
    """执行收到协作式取消请求。"""

    error_code = "run_cancelled"


class RunDeadlineExceededError(TimeoutError, RunStateError):
    """执行超过设定的总时限。"""

    error_code = "run_timeout"


class StepTimeoutError(TimeoutError, RunStateError):
    """当前步骤超过 ``Run.step_timeout_seconds``。"""

    error_code = "step_timeout"


class StepLimitExceededError(RunStateError):
    """最后一步仍请求工具，运行器拒绝执行无法反馈给模型的调用。"""

    error_code = "step_limit_reached"


class NoProgressError(RunStateError):
    """连续重复相同工具请求及结果，策略判定没有进展。"""

    error_code = "no_progress"


class RunSuspendedError(RunStateError):
    """协作式暂停，保持当前步骤，等待恢复或用户审批。"""

    error_code = "run_suspended"


STEP_END_OUTCOMES = {
    StepOutcome.COMPLETED: StepStatus.COMPLETED,
    StepOutcome.FAILED: StepStatus.FAILED,
    StepOutcome.CANCELLED: StepStatus.CANCELLED,
}
RUN_TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


@dataclass
class Step:
    """记录一次模型调用及其产生的工具调用标识。"""

    number: int
    status: StepStatus = StepStatus.RUNNING
    tool_call_ids: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float | None = field(default=None, init=False)

    @property
    def duration_ms(self) -> float:
        """返回步骤耗时；尚未结束时按当前时刻计算。"""
        return elapsed_ms(self.started_at, self.finished_at)


@dataclass
class Run:
    """维护一次执行的状态、步骤、取消请求和时限。

    取消、总时限和步骤时限由运行器在模型调用和工具调用前后检查。同步外部调用
    进行中无法被此状态对象强制中断，因此属于协作式中断：超时在下一个检查点
    生效，并把当前步骤标记为失败。

    传入 ``events`` 后，每次状态迁移都会向该接收端发出事件；接收端在迁移完成
    之后、下一个动作之前收到事件。
    """

    run_id: str
    max_steps: int
    deadline_seconds: float | None = None
    step_timeout_seconds: float | None = None
    events: EventSink | None = field(default=None, repr=False)
    policy: Policy | None = field(default=None, repr=False)
    status: RunStatus = field(default=RunStatus.IDLE, init=False)
    steps: list[Step] = field(default_factory=list, init=False)
    started_at: float | None = field(default=None, init=False)
    finished_at: float | None = field(default=None, init=False)
    no_progress_rounds: int = field(default=0, init=False)
    generation: int = field(default=0, init=False)
    latest_snapshot: RuntimeSnapshot | None = field(default=None, init=False, repr=False)
    _interrupt_requested: bool = field(default=False, init=False, repr=False)
    _cancel_requested: bool = field(default=False, init=False, repr=False)
    _paused_at: float | None = field(default=None, init=False, repr=False)
    _restored: bool = field(default=False, init=False, repr=False)
    _checkpoint: Callable[[], None] | None = field(default=None, init=False, repr=False)
    _relay: EventRelay | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """拒绝无法追踪或无法执行的运行配置。"""
        if not self.run_id.strip():
            raise ValueError("run_id 不能为空")
        if self.max_steps < 1:
            raise ValueError("max_steps 必须至少为 1")
        self._require_positive_timeout(self.deadline_seconds, "deadline_seconds")
        self._require_positive_timeout(
            self.step_timeout_seconds, "step_timeout_seconds"
        )
        self.bind_policy(self.policy or DefaultPolicy(self.max_steps))

    def bind_policy(self, policy: Policy) -> None:
        """启动前绑定策略，兼容旧 Run 时限，采用两者更短的约束。"""
        if self.status is not RunStatus.IDLE:
            raise RuntimeError("运行开始后不能重新绑定策略")
        if self.max_steps != policy.limits.max_steps:
            raise ValueError("运行时状态与策略 max_steps 不匹配")
        self.policy = TimeoutPolicy(
            base=policy, timeout_seconds=self.deadline_seconds,
            step_timeout_seconds=self.step_timeout_seconds,
        )
        self.deadline_seconds = self.policy.limits.deadline_seconds
        self.step_timeout_seconds = self.policy.limits.step_timeout_seconds

    @property
    def duration_ms(self) -> float:
        """返回执行耗时；尚未结束时按当前时刻计算。"""
        if self.started_at is None:
            return 0.0
        return elapsed_ms(
            self.started_at,
            self._paused_at if self._paused_at is not None else self.finished_at,
        )

    @property
    def current_step(self) -> Step | None:
        """返回最后一个步骤；没有步骤时返回 ``None``。"""
        return self.steps[-1] if self.steps else None

    def start(self) -> None:
        """从空闲状态开始执行。"""
        self.check_active()
        if self.status is not RunStatus.IDLE:
            raise RuntimeError("执行只能启动一次")
        self.started_at = monotonic()
        self.status = RunStatus.RUNNING
        self._send(
            RunStarted(
                max_steps=self.max_steps, deadline_seconds=self.deadline_seconds
            )
        )

    def check_active(self) -> None:
        """在外部调用边界检查取消、暂停和时限。

        取消优先于超时，总时限优先于步骤时限；暂停保留进行中的步骤。
        """
        if self._cancel_requested:
            self._cancel_requested = False
            self.cancel()
        if self.status is RunStatus.CANCELLED:
            self._terminate_step(StepOutcome.CANCELLED)
            raise RunCancelledError(f"执行已取消：{self.run_id}")
        if self.status in {RunStatus.SUSPENDED, RunStatus.WAITING_APPROVAL}:
            raise RunSuspendedError("执行正在等待恢复")
        if self.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            return
        if self._interrupt_requested:
            self.suspend()
            self.check_active()  # 暂停事件的订阅方可能同时取消 Run。
        decision = self.policy.should_terminate(self.policy_snapshot())
        if decision is not None:
            self.terminate(decision)

    def policy_snapshot(self, requested_tool_calls: int = 0) -> PolicySnapshot:
        """使用与 Run 状态相同的时钟生成只读策略输入。"""
        now = self._paused_at if self._paused_at is not None else monotonic()
        step = self.current_step
        running_step = step is not None and step.status is StepStatus.RUNNING
        return PolicySnapshot(
            step_number=step.number if step else 0,
            elapsed_seconds=(
                max(0.0, now - self.started_at)
                if self.started_at is not None else 0.0
            ),
            step_elapsed_seconds=(
                max(0.0, now - step.started_at) if running_step else 0.0
            ),
            requested_tool_calls=requested_tool_calls,
            no_progress_rounds=self.no_progress_rounds,
        )

    def terminate(self, decision: Termination, requested_tool_calls: int = 0):
        """执行策略终止决定，生命周期及异常分类仍归 Run。"""
        if decision.kind is TerminationKind.STEP_LIMIT:
            raise self.fail_step_limit(requested_tool_calls)
        if decision.kind is TerminationKind.STEP_TIMEOUT:
            step = self.current_step
            self._terminate_step(StepOutcome.FAILED)
            self._send(
                StepTimeout(
                    duration_ms=step.duration_ms if step else 0.0,
                    timeout_seconds=decision.timeout_seconds or 0.0,
                )
            )
            error = StepTimeoutError(f"步骤超过时限：{self.run_id}")
        elif decision.kind is TerminationKind.RUN_TIMEOUT:
            error = RunDeadlineExceededError(f"执行超过截止时间：{self.run_id}")
        elif decision.kind is TerminationKind.NO_PROGRESS:
            self._send(PolicyTriggered(
                policy="safety", decision="terminate", reason="no_progress",
            ))
            error = NoProgressError("策略检测到连续重复工具往返")
        else:
            raise ValueError("未知策略终止类型")
        self.fail(error)
        raise error

    def begin_step(self, number: int) -> Step:
        """按顺序开始一个模型步骤。"""
        self.check_active()
        if self.status is not RunStatus.RUNNING:
            raise RuntimeError("当前状态不能开始新步骤")
        if number != len(self.steps) + 1 or number > self.max_steps:
            raise ValueError("步骤编号必须连续且不超过 max_steps")
        step = Step(number=number, started_at=monotonic())
        self.steps.append(step)
        self.status = RunStatus.THINKING
        # 步骤时限只约束进行中的步骤，因此先记录步骤再检查时限。
        self.check_active()
        self._send(StepStarted())
        return step

    def interrupt(self) -> None:
        """请求在下一个边界暂停；取消仍是不可恢复的独立语义。"""
        if self.status not in RUN_TERMINAL_STATUSES:
            self._interrupt_requested = True

    def request_cancel(self) -> None:
        """仅记录取消意图，由驱动线程在检查点迁移状态并保存快照。"""
        if self.status not in RUN_TERMINAL_STATUSES:
            self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    @property
    def interrupt_requested(self) -> bool:
        return self._interrupt_requested and self.status not in {
            *RUN_TERMINAL_STATUSES, RunStatus.SUSPENDED, RunStatus.WAITING_APPROVAL,
        }

    def suspend(self, *, approval: bool = False) -> None:
        if self.status in RUN_TERMINAL_STATUSES:
            raise RuntimeError("终态不能暂停")
        self.status = (
            RunStatus.WAITING_APPROVAL if approval else RunStatus.SUSPENDED
        )
        self._paused_at = monotonic()
        self._send(RunSuspended(
            reason="approval" if approval else "interrupted",
        ))

    def resume(self, phase: str) -> None:
        """只恢复从快照构造的新对象，原有 Run 及其终态不被改写。"""
        if not self._restored:
            raise RuntimeError("恢复必须从快照创建新 Run")
        if self.status is RunStatus.CANCELLED:
            raise RunCancelledError("已取消的 Run 不能恢复")
        if self.status is RunStatus.COMPLETED:
            raise RunStateError("已完成的 Run 不能重新执行")
        if phase not in {"model", "tools", "round_end", "step_end", "final"}:
            raise ValueError("未知恢复阶段")
        step = self.current_step
        if phase in {"final", "step_end"} and (
            step is not None and step.status is StepStatus.COMPLETED
        ):
            self.status = RunStatus.RUNNING
        elif phase == "step_end":
            if step is None:
                raise RuntimeError("恢复步骤缺少当前步骤")
            step.status = StepStatus.RUNNING
            step.finished_at = None
            self.status = RunStatus.WAITING_TOOL
        elif phase in {"tools", "round_end", "final"} or (
            phase == "model" and step is not None
            and step.status in {StepStatus.RUNNING, StepStatus.FAILED}
        ):
            if step is None:
                raise RuntimeError("恢复阶段缺少当前步骤")
            step.status = StepStatus.RUNNING
            step.finished_at = None
            self.status = (
                RunStatus.WAITING_TOOL if phase in {"tools", "round_end"}
                else RunStatus.THINKING
            )
        else:
            self.status = RunStatus.RUNNING
        self.finished_at = None
        self._interrupt_requested = False
        self._paused_at = None
        self.generation += 1
        self._restored = False
        self._send(RunResumed(generation=self.generation))

    def reenter_tool_call(self, call_id: str) -> None:
        self.check_active()
        if self.status is not RunStatus.WAITING_TOOL or (
            self.current_step is None
            or call_id not in self.current_step.tool_call_ids
        ):
            raise RuntimeError("恢复工具调用与当前步骤不匹配")
        self.status = RunStatus.EXECUTING_TOOL

    def snapshot_state(self) -> dict:
        now = (
            self._paused_at if self._paused_at is not None
            else self.finished_at if self.finished_at is not None else monotonic()
        )
        elapsed = max(0.0, now - self.started_at) if self.started_at is not None else 0
        return {
            "run_id": self.run_id, "max_steps": self.max_steps,
            "status": self.status.value, "elapsed_seconds": elapsed,
            "deadline_seconds": self.deadline_seconds,
            "step_timeout_seconds": self.step_timeout_seconds,
            "no_progress_rounds": self.no_progress_rounds,
            "generation": self.generation, "sequence": self.relay.sequence,
            "steps": [{
                "number": step.number, "status": step.status.value,
                "call_ids": list(step.tool_call_ids),
                "elapsed_seconds": max(0.0, (
                    step.finished_at if step.finished_at is not None else now
                ) - step.started_at),
            } for step in self.steps],
        }

    @classmethod
    def from_snapshot(cls, data: dict, *, policy: Policy, events=None) -> Run:
        from .snapshot import (
            SnapshotConflictError, SnapshotError, count, seconds, text_value,
        )

        if set(data) != {
            "run_id", "max_steps", "status", "elapsed_seconds", "deadline_seconds",
            "step_timeout_seconds", "no_progress_rounds", "generation", "sequence",
            "steps",
        } or not isinstance(data["steps"], list):
            raise SnapshotError("invalid Run snapshot")
        maximum = count(data["max_steps"], "max_steps", 1)
        if maximum != policy.limits.max_steps:
            raise SnapshotConflictError("Run limit differs from injected policy")
        if len(data["steps"]) > maximum:
            raise SnapshotError("too many steps")
        for name in ("deadline_seconds", "step_timeout_seconds"):
            if data[name] is not None and seconds(data[name], name) <= 0:
                raise SnapshotError("invalid Run timeout")
        try:
            run = cls(
                text_value(data["run_id"], "run_id"), maximum,
                deadline_seconds=data["deadline_seconds"],
                step_timeout_seconds=data["step_timeout_seconds"],
                policy=policy, events=events,
            )
        except (TypeError, ValueError) as error:
            raise SnapshotError("invalid Run configuration") from error
        now = monotonic()
        run.started_at = now - seconds(data["elapsed_seconds"], "elapsed_seconds")
        try:
            run.status = RunStatus(data["status"])
            for index, item in enumerate(data["steps"], 1):
                if set(item) != {"number", "status", "call_ids", "elapsed_seconds"}:
                    raise SnapshotError("invalid Step snapshot")
                if count(item["number"], "step_number", 1) != index:
                    raise SnapshotError("non-contiguous steps")
                ids = item["call_ids"]
                if not isinstance(ids, list) or any(
                    not isinstance(value, str) or not value for value in ids
                ) or len(set(ids)) != len(ids):
                    raise SnapshotError("invalid tool call IDs")
                duration = seconds(item["elapsed_seconds"], "step_elapsed")
                if duration > data["elapsed_seconds"]:
                    raise SnapshotError("step elapsed exceeds Run elapsed")
                step = Step(index, StepStatus(item["status"]), ids, now - duration)
                if index < len(data["steps"]) and step.status is not StepStatus.COMPLETED:
                    raise SnapshotError("unfinished historical step")
                if step.status is not StepStatus.RUNNING:
                    step.finished_at = now
                run.steps.append(step)
        except (ValueError, TypeError) as error:
            raise SnapshotError("invalid Run state") from error
        run.no_progress_rounds = count(data["no_progress_rounds"], "progress")
        run.generation = count(data["generation"], "generation")
        run.relay.sequence = count(data["sequence"], "sequence")
        if run.status in RUN_TERMINAL_STATUSES:
            run.finished_at = now
        run._restored = True
        return run

    def wait_for_tool(self) -> None:
        """记录模型已请求工具或一次工具调用已返回。"""
        self.check_active()
        if self.status not in {RunStatus.THINKING, RunStatus.EXECUTING_TOOL}:
            raise RuntimeError("当前状态不能等待工具")
        self.status = RunStatus.WAITING_TOOL

    def begin_tool_call(self, call_id: str) -> None:
        """记录即将执行的工具调用。"""
        self.check_active()
        if self.status is not RunStatus.WAITING_TOOL:
            raise RuntimeError("当前状态不能执行工具")
        self.steps[-1].tool_call_ids.append(call_id)
        self.status = RunStatus.EXECUTING_TOOL

    def finish_step(self) -> None:
        """结束当前步骤并等待下一次模型调用。"""
        self.check_active()
        step = self.current_step
        if step is None or step.status is not StepStatus.RUNNING:
            raise RuntimeError("当前步骤尚不能结束")
        if self.status not in {RunStatus.THINKING, RunStatus.WAITING_TOOL}:
            raise RuntimeError("当前步骤尚不能结束")
        self._terminate_step(StepOutcome.COMPLETED)
        self.status = RunStatus.RUNNING

    def complete(self) -> None:
        """在最后一个步骤结束后标记整次执行完成。"""
        self.check_active()
        if self.status is not RunStatus.RUNNING or not self.steps:
            raise RuntimeError("执行尚不能完成")
        self.status = RunStatus.COMPLETED
        self.finished_at = monotonic()
        self._send(RunCompleted(steps=len(self.steps), duration_ms=self.duration_ms))

    def fail(self, error: BaseException | None = None) -> None:
        """标记执行失败，并保留已完成步骤的记录。

        已处于终态时不做任何事，因此同一次 Run 只会产生一个终态事件。
        """
        if self.status in RUN_TERMINAL_STATUSES:
            return
        self._terminate_step(StepOutcome.FAILED)
        self.status = RunStatus.FAILED
        self.finished_at = self._paused_at if self._paused_at is not None else monotonic()
        self._send(
            RunFailed(
                steps=len(self.steps),
                duration_ms=self.duration_ms,
                error=describe_error(error) or ErrorInfo(error_code="run_failed"),
            )
        )

    def cancel(self) -> None:
        """请求取消；运行器在下一次检查时停止后续调用。

        只标记终态：取消事件在请求时发出，进行中步骤的 ``StepEnd`` 由运行器在
        下一个检查点写出；已暂停的步骤在此直接结束。取消事件先于步骤结束事件。
        """
        if self.status in RUN_TERMINAL_STATUSES:
            return
        paused = self.status in {RunStatus.SUSPENDED, RunStatus.WAITING_APPROVAL}
        self.status = RunStatus.CANCELLED
        self.finished_at = self._paused_at if self._paused_at is not None else monotonic()
        self._send(RunCancelled(steps=len(self.steps), duration_ms=self.duration_ms))
        if paused:
            # 暂停后没有驱动循环继续检查，因此在此处结束步骤并持久化取消。
            self._terminate_step(StepOutcome.CANCELLED)
        if self._checkpoint is not None:
            self._checkpoint()

    def fail_step_limit(self, requested_tool_calls: int) -> StepLimitExceededError:
        """记录最后一步仍请求工具，并返回供运行器抛出的异常。"""
        self._send(
            StepLimitReached(
                max_steps=self.max_steps, requested_tool_calls=requested_tool_calls
            )
        )
        error = StepLimitExceededError(f"Exceeded max steps ({self.max_steps})")
        self.fail(error)
        return error

    def create_relay(self, sink: EventSink | None) -> EventRelay:
        """创建本次执行的事件中继，并交给运行器共用。

        中继只创建一次：之后无论谁再调用，都返回同一个中继，从而保证整次 Run
        共享一个序列号空间和同一个接收端。运行器因此必须在开始执行前调用一次。
        """
        if self._relay is None:
            self._relay = EventRelay(sink)
        return self._relay

    @property
    def relay(self) -> EventRelay:
        """返回本次执行的事件中继；尚未绑定时按 ``events`` 创建。"""
        return self.create_relay(self.events)

    @staticmethod
    def _require_positive_timeout(value: float | None, name: str) -> None:
        """拒绝非有限或非正的时限配置。"""
        if value is not None and (not isfinite(value) or value <= 0):
            raise ValueError(f"{name} 必须是有限的正数")

    def _terminate_step(self, outcome: StepOutcome) -> None:
        """结束当前步骤并发出 ``StepEnd``；没有进行中的步骤时不做任何事。"""
        step = self.current_step
        if step is None or step.status is not StepStatus.RUNNING:
            return
        step.status = STEP_END_OUTCOMES[outcome]
        step.finished_at = self._paused_at if self._paused_at is not None else monotonic()
        self._send(
            StepEnd(
                outcome=outcome,
                duration_ms=step.duration_ms,
                tool_call_count=len(step.tool_call_ids),
            )
        )

    def _send(self, event: RunEvent) -> None:
        """发出一次状态迁移产生的事件；没有接收端时同样安全。"""
        self.relay.emit(self, event)
