"""一次 Agent 执行及其步骤的最小运行时状态。"""

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from time import monotonic


class RunStatus(str, Enum):
    """一次执行可观察到的状态。"""

    IDLE = "idle"
    RUNNING = "running"
    THINKING = "thinking"
    WAITING_TOOL = "waiting_tool"
    EXECUTING_TOOL = "executing_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """单个模型步骤的结束状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunCancelledError(RuntimeError):
    """执行收到协作式取消请求。"""


class RunDeadlineExceededError(TimeoutError):
    """执行超过设定的总时限。"""


@dataclass
class Step:
    """记录一次模型调用及其产生的工具调用标识。"""

    number: int
    status: StepStatus = StepStatus.RUNNING
    tool_call_ids: list[str] = field(default_factory=list)


@dataclass
class Run:
    """维护一次执行的状态、步骤、取消请求和总时限。

    取消及截止时间由运行器在模型调用和工具调用前后检查。同步外部调用
    进行中无法被此状态对象强制中断，因此属于协作式取消。
    """

    run_id: str
    max_steps: int
    deadline_seconds: float | None = None
    status: RunStatus = field(default=RunStatus.IDLE, init=False)
    steps: list[Step] = field(default_factory=list, init=False)
    started_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """拒绝无法追踪或无法执行的运行配置。"""
        if not self.run_id.strip():
            raise ValueError("run_id 不能为空")
        if self.max_steps < 1:
            raise ValueError("max_steps 必须至少为 1")
        if self.deadline_seconds is not None and (
            not isfinite(self.deadline_seconds) or self.deadline_seconds <= 0
        ):
            raise ValueError("deadline_seconds 必须是有限的正数")

    def start(self) -> None:
        """从空闲状态开始执行。"""
        self.check_active()
        if self.status is not RunStatus.IDLE:
            raise RuntimeError("执行只能启动一次")
        self.started_at = monotonic()
        self.status = RunStatus.RUNNING

    def check_active(self) -> None:
        """在外部调用边界检查取消请求和总时限。"""
        if self.status is RunStatus.CANCELLED:
            raise RunCancelledError(f"执行已取消：{self.run_id}")
        if (
            self.started_at is not None
            and self.deadline_seconds is not None
            and self.status not in {RunStatus.COMPLETED, RunStatus.FAILED}
            and monotonic() - self.started_at >= self.deadline_seconds
        ):
            self.fail()
            raise RunDeadlineExceededError(f"执行超过截止时间：{self.run_id}")

    def begin_step(self, number: int) -> Step:
        """按顺序开始一个模型步骤。"""
        self.check_active()
        if self.status is not RunStatus.RUNNING:
            raise RuntimeError("当前状态不能开始新步骤")
        if number != len(self.steps) + 1 or number > self.max_steps:
            raise ValueError("步骤编号必须连续且不超过 max_steps")
        step = Step(number=number)
        self.steps.append(step)
        self.status = RunStatus.THINKING
        return step

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
        if self.status not in {RunStatus.THINKING, RunStatus.WAITING_TOOL}:
            raise RuntimeError("当前步骤尚不能结束")
        self.steps[-1].status = StepStatus.COMPLETED
        self.status = RunStatus.RUNNING

    def complete(self) -> None:
        """在最后一个步骤结束后标记整次执行完成。"""
        self.check_active()
        if self.status is not RunStatus.RUNNING or not self.steps:
            raise RuntimeError("执行尚不能完成")
        self.status = RunStatus.COMPLETED

    def fail(self) -> None:
        """标记执行失败，并保留已完成步骤的记录。"""
        if self.status in {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}:
            return
        if self.steps and self.steps[-1].status is StepStatus.RUNNING:
            self.steps[-1].status = StepStatus.FAILED
        self.status = RunStatus.FAILED

    def cancel(self) -> None:
        """请求取消；运行器在下一次检查时停止后续调用。"""
        if self.status in {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}:
            return
        if self.steps and self.steps[-1].status is StepStatus.RUNNING:
            self.steps[-1].status = StepStatus.CANCELLED
        self.status = RunStatus.CANCELLED
