"""工具模块的统一调用入口：策略、执行、进度和工具事件。"""

from typing import Any
from dataclasses import replace
from copy import deepcopy

from slothy.core.events import (
    RunEvent,
    ToolCallEnd,
    ToolCallStart,
    ToolError,
    ToolProgress,
    ToolTimeout,
    ToolTimeoutError,
    describe_error,
)
from slothy.core.events.emitter import EventEmitter
from slothy.core.model.model_models import ToolCall
from slothy.core.policy import Policy, PolicyEngine
from slothy.core.policy.evaluation import check_tool_call
from slothy.core.policy.session import PolicySession

from .executor import ToolExecutor
from .tool_models import ProgressReport, ToolContext, ToolRegistry, ToolResult
from .journal import ToolJournal
from .replay import IdempotencyUncertainError


class ToolSession:
    """隔离工具系统内部变化；注册表仍只提供定义，执行器仍负责校验与授权。"""

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        policy: Policy | PolicyEngine,
        events: EventEmitter,
        resilience: PolicySession | None = None,
        journal: ToolJournal | None = None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._policy = policy
        self._events = events
        self._resilience = resilience
        self._journal = journal

    @property
    def definitions(self) -> list[dict[str, Any]]:
        """读取本次运行供模型使用的工具定义；失败交由运行器结束 Run。"""
        return self._registry.definitions()

    def validate_recovery(self) -> None:
        """先核对未完成调用的实现版本与安全声明，再消费审批决定。"""
        from slothy.core.runtime.snapshot import SnapshotConflictError

        if self._journal is None:
            return
        lookup = getattr(self._registry, "get_tool", None)
        for record in self._journal.records.values():
            if record["status"] == "completed":
                continue
            call = ToolCall(record["call_id"], record["name"], record["arguments"])
            try:
                definition = lookup(call.name) if lookup is not None else None
            except KeyError as error:
                raise SnapshotConflictError("pending tool is unavailable") from error
            self._journal.prepare(
                call, record["step"], definition,
                legacy_safe=self._legacy_safe(call.name),
            )

    def _legacy_safe(self, name: str) -> bool:
        candidate = self._policy
        while candidate is not None:
            if name in getattr(candidate, "retry_tools", ()):
                return True
            candidate = getattr(candidate, "base", None)
        return False

    def tool_call(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """处理一次请求；受控错误返回模型，执行器异常原样向外传播。"""
        identity = None
        if self._journal is not None:
            step = self._resilience.state.current_step.number
            identity = self._journal.completed_identity(call, step)
            if identity is not None:
                cached = self._journal.cached(identity)
                self._emit_result_once(identity, call, cached, 0.0)
                return cached
        lookup = getattr(self._registry, "get_tool", None)
        definition = lookup(call.name) if lookup is not None else None
        if self._journal is not None:
            identity = self._journal.prepare(
                call, step, definition, legacy_safe=self._legacy_safe(call.name),
            )
        self._events.emit(
            ToolCallStart(
                call_id=call.call_id,
                name=call.name,
                argument_keys=tuple(sorted(call.arguments)),
            )
        )
        blocked = check_tool_call(self._policy, call, context.run_id, self._events)
        if blocked is not None:
            result = ToolResult(output={"error": blocked}, is_error=True)
            if identity is not None:
                self._journal.completed(identity, result)
            self._emit_result_once(identity, call, result, 0.0)
            return result

        started_at = self._events.clock()

        def attempt(timeout: float | None) -> ToolResult:
            # 每次尝试拥有独立标记，旧回调在重试时也不会复活。
            active = True

            def on_progress(report: ProgressReport) -> None:
                if active:
                    self._events.emit(ToolProgress(
                        call_id=call.call_id, name=call.name,
                        completed=report.completed, total=report.total,
                        message=report.message,
                    ))

            execution_context = (
                replace(context, timeout_seconds=timeout)
                if timeout is not None else context
            )
            if identity is not None:
                execution_context, cached = self._journal.authorize(
                    identity, call, execution_context, self._executor,
                )
                if cached is not None:
                    return cached
                self._resilience.state.check_active()
                self._journal.started(identity)
            try:
                result = self._executor.execute(
                    deepcopy(call), execution_context,
                    on_progress if self._events.enabled else None,
                )
                if identity is not None:
                    self._journal.completed(identity, result)
                return result
            except IdempotencyUncertainError:
                if identity is None:
                    raise
                self._journal.failed(identity)
                self._journal.request_approval(identity, "execution_unknown")
                raise
            except Exception:
                if identity is not None:
                    self._journal.failed(identity)
                raise
            finally:
                active = False

        def on_failure(error: Exception) -> None:
            self._events.emit(
                _tool_failure_event(call, self._events.elapsed(started_at), error)
            )

        if self._resilience is not None:
            declared_timeout = (
                definition.timeout_seconds if definition is not None else None
            )
            if context.timeout_seconds is not None:
                declared_timeout = min(
                    declared_timeout or context.timeout_seconds,
                    context.timeout_seconds,
                )
            result = self._resilience.invoke(
                "tool", attempt, on_failure, tool_name=call.name,
                timeout_seconds=declared_timeout,
                recover=lambda error: ToolResult(
                    output={
                        "error": "工具执行失败",
                        "code": describe_error(error).error_code,
                    },
                    is_error=True,
                ),
                start_attempt=(
                    self._journal.records[identity]["attempts"] + 1
                    if identity is not None else 1
                ),
                elapsed_seconds=(
                    self._journal.records[identity]["elapsed_seconds"]
                    if identity is not None else 0.0
                ),
                replay_guarded=(
                    identity is not None
                    and getattr(definition, "replay_safety", None) is not None
                ),
            )
        else:
            try:
                result = attempt(context.timeout_seconds)
            except Exception as error:
                on_failure(error)
                raise

        if identity is not None and self._journal.cached(identity) is None:
            self._journal.completed(identity, result)
        self._emit_result_once(identity, call, result, self._events.elapsed(started_at))
        return result

    def _emit_result_once(self, identity, call, result, duration):
        if identity is not None:
            record = self._journal.records[identity]
            if record["end_emitted"]:
                return
            record["end_emitted"] = True
            self._journal.save()
        self._emit_result(call, result, duration)

    def _emit_result(
        self, call: ToolCall, result: ToolResult, duration_ms: float
    ) -> None:
        self._events.emit(
            ToolCallEnd(
                call_id=call.call_id,
                name=call.name,
                duration_ms=duration_ms,
                is_error=result.is_error,
                output_size=len(result.to_model_output()),
            )
        )


def _tool_failure_event(
    call: ToolCall, duration_ms: float, error: BaseException
) -> RunEvent:
    """只有统一分类的异常映射为工具超时，其余映射为工具错误。"""
    event_type = ToolTimeout if isinstance(error, ToolTimeoutError) else ToolError
    return event_type(
        call_id=call.call_id,
        name=call.name,
        duration_ms=duration_ms,
        error=describe_error(error),
    )
