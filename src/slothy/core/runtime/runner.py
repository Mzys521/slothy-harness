"""智能体循环：通过模块入口编排模型与工具，控制 Run 的生命周期。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slothy.core.context import Context
from slothy.core.model import ModelProvider
from slothy.core.policy import Policy, PolicyEngine
from slothy.core.policy.resilience import resolve_policy
from slothy.core.tools import ApprovalDecision, ToolContext, ToolExecutor, ToolRegistry

# 保留既有指标常量的导入位置；实际观测逻辑归 observation 模块。
from .observation import (
    RUN_DURATION_METRIC as RUN_DURATION_METRIC,
    STEP_DURATION_METRIC as STEP_DURATION_METRIC,
)
from .runner_models import RunnerResult
from .state import Run
from .execution import RunExecution
from .snapshot import RuntimeSnapshot, SnapshotStore

if TYPE_CHECKING:
    from slothy.core.events import EventSink


class AgentRunner:
    """只管理运行和步骤；消息、模型、工具及策略细节由所属模块处理。"""

    def __init__(
        self,
        model: ModelProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        max_steps: int | None = None,
        policy: Policy | PolicyEngine | None = None,
        context: Context | None = None,
        token_budget: int | None = None,
        snapshot_store: SnapshotStore | None = None,
    ) -> None:
        self.model = model
        self.registry = registry
        self.executor = executor
        self.policy = resolve_policy(policy, max_steps)
        self.max_steps = self.policy.limits.max_steps
        self.context = context
        self.token_budget = token_budget
        self.snapshot_store = snapshot_store
        self.latest_snapshot: RuntimeSnapshot | None = None
        self._current_run: Run | None = None
        self._snapshot_stores: dict[str, SnapshotStore] = {}

    @property
    def current_run(self) -> Run | None:
        """当前驱动的 Run；恢复成功后指向新一代对象，供宿主控制执行。"""
        return self._current_run

    def run(
        self,
        user_input: str,
        *,
        context: ToolContext,
        runtime: Run | None = None,
        events: EventSink | None = None,
    ) -> RunnerResult:
        """运行至回答或策略终止；失败处置归策略，终态仍由 Run 维护。"""
        return RunExecution.start(
            self, user_input, context, runtime, events,
        ).drive()

    def resume(
        self, snapshot: RuntimeSnapshot, *, context: ToolContext,
        approval: ApprovalDecision | None = None, events: EventSink | None = None,
    ) -> RunnerResult:
        """从快照创建新 Run 并继续；审批只接受宿主显式提交的决定。"""
        return RunExecution.restore(
            self, snapshot, context, events, approval,
        ).drive()

    def cancel_snapshot(
        self, snapshot: RuntimeSnapshot, *, context: ToolContext,
        events: EventSink | None = None,
    ) -> RunnerResult:
        """可信宿主取消尚未接管的快照；不会调用模型或工具。"""
        return RunExecution.cancel_saved(self, snapshot, context, events)
