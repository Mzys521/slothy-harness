"""运行用例；依赖注入的 Core 接口，不导入具体 SDK、数据库或 main。"""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from slothy.application.dto import (
    ApprovalDTO, ApprovalDecisionDTO, RunDTO, StepDTO, ToolDTO,
)
from slothy.application.dto.requests import CreateRunRequest
from slothy.application.errors import ApplicationError, execution_error
from slothy.core.runtime import (
    AgentRunner, Run, RunStatus, RuntimeSnapshot, SnapshotError, SnapshotStore,
)
from slothy.core.tools import ApprovalDecision, ApprovalRequest, ToolContext, ToolRegistry

from .observation import RuntimeObservation
from .memory_service import MemoryService
from slothy.application.dto.inspection import context_inspection, counters


@dataclass
class _RunEntry:
    owner_id: str
    runner: AgentRunner
    runtime: Run
    user_input: str | None
    observation: RuntimeObservation | None = None
    lock: RLock = field(default_factory=RLock)
    busy: bool = False
    snapshot: RuntimeSnapshot | None = None
    approval: ApprovalRequest | None = None
    decision: ApprovalDecision | None = None
    output: str | None = None
    error_code: str | None = None
    cancel_pending: bool = False
    interrupt_pending: bool = False
    handoff_pending: bool = False


class RuntimeService:
    def __init__(
        self, runner_factory: Callable[[], AgentRunner], registry: ToolRegistry,
        *, snapshot_store: SnapshotStore | None = None, event_capacity: int = 1000,
        memory_service: MemoryService | None = None,
    ):
        if type(event_capacity) is not int or event_capacity < 1:
            raise ValueError("event_capacity must be a positive integer")
        self._runner_factory = runner_factory
        self._registry = registry
        self._snapshot_store = snapshot_store
        self._event_capacity = event_capacity
        self._memory_service = memory_service
        self._entries: dict[str, _RunEntry] = {}
        self._lock = RLock()

    def create_run(self, user_input: str, *, actor_id: str) -> RunDTO:
        user_input = CreateRunRequest.parse({"user_input": user_input}).user_input
        runner = self._new_runner()
        seed = getattr(runner.context, "set_recent_memories", None)
        if self._memory_service is not None and callable(seed):
            try:
                seed(self._memory_service.recent_completed(actor_id=actor_id))
            except Exception:
                raise ApplicationError("memory_error", "无法读取已完成任务的历史记忆。") from None
        run = Run(uuid4().hex, runner.max_steps, policy=runner.policy)
        entry = _RunEntry(actor_id, runner, run, user_input)
        self._register(entry)
        return self._view(entry)

    def register_saved_run(self, run_id: str, *, owner_id: str) -> RunDTO:
        """可信宿主先确认归属，再接入已保存 Run；不向前端开放快照上传。"""
        if self._snapshot_store is None:
            raise ApplicationError("not_configured", "未配置快照存储。")
        try:
            snapshot = self._snapshot_store.load(run_id)
            if snapshot is None:
                raise ApplicationError("run_not_found", "执行不存在。")
            runner = self._new_runner()
            data = snapshot.to_dict()
            run = Run.from_snapshot(data["run"], policy=runner.policy)
            entry = _RunEntry(owner_id, runner, run, None, snapshot=snapshot)
            entry.approval = self._saved_approval(snapshot)
            if run.status is RunStatus.COMPLETED:
                entry.output = data["cursor"]["response"]["text"]
            self._register(entry)
            return self._view(entry)
        except ApplicationError:
            raise
        except Exception as error:
            raise execution_error(error, run_id) from error

    def execute_run(self, run_id: str, *, actor_id: str) -> RunDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            self._not_busy(entry)
            if entry.runtime.status is not RunStatus.IDLE or entry.user_input is None:
                raise ApplicationError("invalid_state", "只有新建执行可以启动。", run_id=run_id)
            entry.busy = True
        return self._drive(entry, resume=False)

    def resume_run(self, run_id: str, expected_revision: int, *, actor_id: str) -> RunDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            self._not_busy(entry)
            if entry.runtime.status in {RunStatus.IDLE, RunStatus.COMPLETED, RunStatus.CANCELLED}:
                raise ApplicationError("invalid_state", "当前执行不能恢复。", run_id=run_id)
            self._check_revision(entry, expected_revision)
            if entry.approval is not None and entry.decision is None:
                raise ApplicationError("approval_required", "请先批准或拒绝待审批工具。", run_id=run_id)
            entry.busy = True
            entry.handoff_pending = True
        return self._drive(entry, resume=True)

    def get_run(self, run_id: str, *, actor_id: str) -> RunDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            return self._view(entry)

    def inspect_run(self, run_id: str, *, actor_id: str) -> dict:
        """所属用户的展示投影；不导出消息、结果、工具日志或原始快照。"""
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            snapshot = entry.runner.latest_snapshot or entry.snapshot
            data = snapshot.to_dict() if snapshot else {}
            context = data.get("context", {})
            report = getattr(entry.runner.context, "last_report", None)
            state, report, config = context_inspection(context, report,
                run_id=run_id, user_input=entry.user_input)
            return deepcopy({
                "run": self._view(entry).to_dict(), "task_state": state,
                "context_report": report, "context_config": config,
                "model": getattr(entry.runner.model, "model", None),
                "usage": counters(data.get("model", {}).get("usage"),
                                  ("total_tokens", "prompt_tokens", "completion_tokens")),
            })

    def list_runs(self, *, actor_id: str, offset: int = 0, limit: int = 100) -> list[RunDTO]:
        with self._lock:
            entries = [entry for entry in self._entries.values() if entry.owner_id == actor_id]
        result = []
        for entry in entries[offset:offset + limit]:
            with entry.lock:
                result.append(self._view(entry))
        return result

    def cancel_run(self, run_id: str, *, actor_id: str) -> RunDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            if entry.runtime.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return self._view(entry)
            if entry.busy:
                if entry.runner.current_run is not None and not entry.handoff_pending:
                    entry.runner.current_run.request_cancel()
                else:
                    entry.cancel_pending = True
            else:
                try:
                    if entry.user_input is None and entry.runner.current_run is None:
                        entry.busy = True
                        entry.runner.cancel_snapshot(
                            entry.snapshot, context=ToolContext(run_id), events=entry.observation,
                        )
                    else:
                        entry.runtime.cancel()
                except Exception as error:
                    mapped = execution_error(error, run_id)
                    entry.error_code = mapped.dto.code
                    raise mapped from error
                finally:
                    entry.busy = False
                    entry.decision = None
                    self._refresh(entry)
            return self._view(entry)

    def interrupt_run(self, run_id: str, *, actor_id: str) -> RunDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            if entry.runtime.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                raise ApplicationError("invalid_state", "终态不能暂停。", run_id=run_id)
            if not entry.busy:
                if entry.runtime.status not in {RunStatus.SUSPENDED, RunStatus.WAITING_APPROVAL}:
                    raise ApplicationError("invalid_state", "只有正在执行的 Run 可以请求暂停。", run_id=run_id)
            else:
                if entry.runner.current_run is not None and not entry.handoff_pending:
                    entry.runner.current_run.interrupt()
                else:
                    entry.interrupt_pending = True
            return self._view(entry)

    def get_approval(self, run_id: str, *, actor_id: str) -> ApprovalDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            self._not_busy(entry)
            request = self._require_approval(entry)
            return ApprovalDTO(
                request.request_id, request.run_id, request.step_number,
                request.call_id, request.tool_name, request.fingerprint,
                request.attempt, request.reason, deepcopy(request.arguments),
                entry.snapshot.revision, self._decision_name(entry),
            )

    def decide_tool(
        self, run_id: str, request_id: str, expected_revision: int,
        *, approved: bool, actor_id: str,
    ) -> ApprovalDecisionDTO:
        entry = self._entry(run_id, actor_id)
        with entry.lock:
            self._not_busy(entry)
            request = self._require_approval(entry)
            self._check_revision(entry, expected_revision)
            if request.request_id != request_id:
                raise ApplicationError("approval_conflict", "审批请求已改变。", run_id=run_id)
            if entry.decision is not None:
                raise ApplicationError("approval_already_decided", "本次审批已经作出决定。", run_id=run_id)
            entry.decision = ApprovalDecision(request_id, approved, actor_id)
            return ApprovalDecisionDTO(request_id, approved, actor_id, expected_revision)

    def list_tools(self) -> list[ToolDTO]:
        result = []
        for definition in self._registry.definitions():
            tool = self._registry.get_tool(definition["name"])
            result.append(ToolDTO(
                definition["name"], definition["description"], definition["parameters"],
                tool.replay_safety.value if tool else "unspecified",
                tool.execution_version if tool else None,
                tool.timeout_seconds if tool else None,
            ))
        return result

    def get_events(self, run_id: str, *, actor_id: str, after: int = 0, limit: int = 100):
        return self._entry(run_id, actor_id).observation.page(after=after, limit=limit)

    def subscribe_events(self, run_id: str, listener: Callable, *, actor_id: str) -> str:
        return self._entry(run_id, actor_id).observation.subscribe(listener)

    def unsubscribe_events(self, run_id: str, subscription_id: str, *, actor_id: str) -> bool:
        return self._entry(run_id, actor_id).observation.unsubscribe(subscription_id)

    def _drive(self, entry: _RunEntry, *, resume: bool) -> RunDTO:
        run_id = entry.runtime.run_id
        with entry.lock:
            decision, entry.decision = entry.decision, None
            snapshot = entry.snapshot
            entry.error_code = None
        try:
            context = ToolContext(run_id, metadata={"actor_id": entry.owner_id})
            if resume:
                result = entry.runner.resume(
                    snapshot, context=context, approval=decision, events=entry.observation,
                )
            else:
                result = entry.runner.run(
                    entry.user_input, context=context, runtime=entry.runtime,
                    events=entry.observation,
                )
            with entry.lock:
                entry.runtime = result.run
                entry.snapshot, entry.approval = result.snapshot, result.approval
                entry.output = result.output if result.run.status is RunStatus.COMPLETED else None
            if result.run.status is RunStatus.COMPLETED and self._memory_service is not None:
                self._remember_completed(entry)
        except Exception as error:
            mapped = error if isinstance(error, ApplicationError) else execution_error(error, run_id)
            with entry.lock:
                entry.error_code = mapped.dto.code
            raise mapped from error
        finally:
            with entry.lock:
                entry.busy = False
                entry.handoff_pending = False
                entry.cancel_pending = entry.interrupt_pending = False
                self._refresh(entry)
        with entry.lock:
            return self._view(entry)

    def _remember_completed(self, entry):
        # 完成事件早于完成快照提交，因此不能在 RunCompleted 监听器中写记忆。
        # 只有 runner 返回后，最终回答与完成快照才已一起提交。
        with entry.lock:
            text = entry.user_input
            if text is None and entry.snapshot is not None:
                context = entry.snapshot.to_dict()["context"]
                text = context.get("task_state", {}).get("goal")
                if not text:
                    history = context.get("history", context.get("active", context.get("messages", [])))
                    text = next((m["content"] for m in history if m.get("role") == "user"), None)
            view = self._view(entry)
        try:
            self._memory_service.remember_completed_run(view, text, actor_id=entry.owner_id)
        except Exception:
            # 已完成结果仍可查询；不能把独立记忆存储故障改写为 Runtime 失败。
            raise ApplicationError("memory_error", "任务已完成，但历史记忆保存失败。结果已保留，请检查记忆存储。",
                                   run_id=entry.runtime.run_id) from None

    def _on_event(self, entry: _RunEntry, event):
        with entry.lock:
            current = entry.runner.current_run
            if current is not None:
                entry.runtime = current
            if event.event_type == "run.resumed":
                entry.handoff_pending = False
            if entry.cancel_pending and not entry.handoff_pending:
                entry.cancel_pending = False
                entry.runtime.request_cancel()
            if entry.interrupt_pending and not entry.handoff_pending:
                entry.interrupt_pending = False
                entry.runtime.interrupt()
            return entry.runtime.status.value, entry.runtime.generation

    def _refresh(self, entry: _RunEntry):
        current = entry.runner.current_run
        if current is not None:
            entry.runtime = current
        snapshot = entry.runner.latest_snapshot or entry.runtime.latest_snapshot or entry.snapshot
        entry.snapshot = snapshot
        entry.approval = self._saved_approval(snapshot)

    def _view(self, entry: _RunEntry) -> RunDTO:
        run = entry.runtime
        snapshot = run.latest_snapshot or entry.snapshot
        approval = entry.approval if run.status is RunStatus.WAITING_APPROVAL else None
        return RunDTO(
            run.run_id, run.status.value, entry.busy, run.max_steps, len(run.steps),
            [StepDTO(step.number, step.status.value, list(step.tool_call_ids), step.duration_ms)
             for step in run.steps], run.duration_ms, run.generation,
            snapshot.revision if snapshot else None, entry.output, entry.error_code,
            approval.request_id if approval else None, self._decision_name(entry),
            (entry.cancel_pending or run.cancel_requested) if entry.busy else False,
            (entry.interrupt_pending or run.interrupt_requested) if entry.busy else False,
            entry.observation.cursor, entry.observation.failure_count,
        )

    def _new_runner(self) -> AgentRunner:
        try:
            runner = self._runner_factory()
            if not isinstance(runner, AgentRunner) or runner.current_run is not None or (
                self._snapshot_store is not None
                and runner.snapshot_store is not self._snapshot_store
            ):
                raise ValueError("factory must inject the configured SnapshotStore")
            return runner
        except Exception as error:
            raise ApplicationError("invalid_configuration", "运行器依赖组装无效。") from error

    def _register(self, entry: _RunEntry):
        if not isinstance(entry.owner_id, str) or not entry.owner_id.strip():
            raise ApplicationError("invalid_request", "宿主身份不能为空。")
        with self._lock:
            if entry.runtime.run_id in self._entries:
                raise ApplicationError("run_exists", "执行已经登记。")
            if any(
                old.runner is entry.runner or (
                    entry.runner.context is not None and old.runner.context is entry.runner.context
                ) for old in self._entries.values()
            ):
                raise ApplicationError("invalid_configuration", "每个 Run 必须使用独立的 Runner 和 Context。")
            entry.observation = RuntimeObservation(
                lambda event: self._on_event(entry, event), capacity=self._event_capacity,
            )
            if entry.user_input is not None:
                entry.runtime.create_relay(entry.observation)
            self._entries[entry.runtime.run_id] = entry

    def _entry(self, run_id: str, actor_id: str) -> _RunEntry:
        with self._lock:
            entry = self._entries.get(run_id)
        if entry is None or entry.owner_id != actor_id:
            raise ApplicationError("run_not_found", "执行不存在。", run_id=run_id)
        return entry

    @staticmethod
    def _not_busy(entry: _RunEntry):
        if entry.busy:
            raise ApplicationError("run_busy", "执行已被另一操作驱动。", run_id=entry.runtime.run_id)

    @staticmethod
    def _decision_name(entry: _RunEntry) -> str | None:
        if entry.decision is None:
            return None
        return "approved" if entry.decision.approved else "rejected"

    @staticmethod
    def _saved_approval(snapshot: RuntimeSnapshot | None) -> ApprovalRequest | None:
        if snapshot is None:
            return None
        pending = [record["pending"] for record in snapshot.to_dict()["tools"]["records"].values()
                   if record["pending"] is not None]
        if len(pending) > 1:
            raise SnapshotError("multiple pending approvals")
        return ApprovalRequest(**pending[0]) if pending else None

    @staticmethod
    def _require_approval(entry: _RunEntry) -> ApprovalRequest:
        if entry.runtime.status is not RunStatus.WAITING_APPROVAL or entry.approval is None:
            raise ApplicationError("no_pending_approval", "当前没有待审批工具。", run_id=entry.runtime.run_id)
        return entry.approval

    def _check_revision(self, entry: _RunEntry, revision: int):
        snapshot = entry.snapshot
        if snapshot is None or snapshot.revision != revision:
            raise ApplicationError("snapshot_conflict", "快照版本已改变。", run_id=entry.runtime.run_id)
        if self._snapshot_store is not None:
            try:
                stored = self._snapshot_store.load(entry.runtime.run_id)
            except Exception as error:
                raise execution_error(
                    SnapshotError("store failed"), entry.runtime.run_id,
                ) from error
            if stored is None or stored.to_dict() != snapshot.to_dict():
                raise ApplicationError("snapshot_conflict", "快照版本已改变。", run_id=entry.runtime.run_id)
