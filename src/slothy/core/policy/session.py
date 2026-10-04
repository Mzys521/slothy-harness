"""每次运行独立的策略执行入口：终止、调用预算、重试与进展。"""

from __future__ import annotations

from hashlib import sha256
from json import dumps
from typing import TYPE_CHECKING, Callable, TypeVar

from slothy.core.events import LLMTimeoutError, PolicyTriggered, ToolTimeoutError
from slothy.core.events.emitter import EventEmitter

from .resilience import ErrorAction, FailureContext, Policy, _minimum

if TYPE_CHECKING:
    from slothy.core.model import ToolCall
    from slothy.core.runtime.state import Run
    from slothy.core.tools import ToolResult

T = TypeVar("T")


class PolicySession:
    def __init__(
        self, state: Run, policy: Policy, events: EventEmitter, *, restored=False,
    ) -> None:
        if not restored:
            state.bind_policy(policy)
        self.state = state
        self.policy = state.policy
        self.events = events
        self._previous_round: bytes | None = None
        self._round: list[str] = []

    def snapshot_state(self) -> dict:
        return {
            "previous_round": (
                self._previous_round.hex() if self._previous_round is not None else None
            ),
            "round": list(self._round),
        }

    def restore_state(self, data: dict) -> None:
        from slothy.core.runtime.snapshot import SnapshotError

        if set(data) != {"previous_round", "round"} or (
            not isinstance(data["round"], list)
            or any(not isinstance(value, str) for value in data["round"])
        ):
            raise SnapshotError("invalid policy snapshot")
        previous = data["previous_round"]
        try:
            prepared = bytes.fromhex(previous) if previous is not None else None
        except (TypeError, ValueError) as error:
            raise SnapshotError("invalid progress digest") from error
        if prepared is not None and len(prepared) != 32:
            raise SnapshotError("invalid progress digest length")
        self._previous_round, self._round = prepared, list(data["round"])

    def should_terminate(self, requested_tool_calls: int = 0) -> None:
        self.state.check_active()
        decision = self.policy.should_terminate(
            self.state.policy_snapshot(requested_tool_calls)
        )
        if decision is not None:
            self.state.terminate(decision, requested_tool_calls)

    def invoke(
        self,
        operation: str,
        call: Callable[[float | None], T],
        on_failure: Callable[[Exception], None],
        *,
        tool_name: str = "",
        streamed: Callable[[], bool] = lambda: False,
        timeout_seconds: float | None = None,
        recover: Callable[[Exception], T] | None = None,
        start_attempt: int = 1,
        elapsed_seconds: float = 0.0,
        replay_guarded: bool = False,
    ) -> T:
        """重试不增加轮次；每个尝试重新检查取消和剩余预算。

        timeout_seconds 与策略调用时限共同约束整个逻辑调用（包含重试），
        不会因失败而重置预算。同步实现只在调用边界强制检查。
        """
        started_at = self.events.clock() - elapsed_seconds
        attempt = start_attempt
        limits = self.policy.limits
        initial = (
            limits.model_timeout_seconds if operation == "model"
            else limits.tool_timeout_seconds
        )
        call_limit = _minimum(initial, timeout_seconds)
        while True:
            self.state.check_active()
            remaining = _minimum(
                self.policy.timeout_for(operation, self.state.policy_snapshot()),
                call_limit - (self.events.clock() - started_at)
                if call_limit is not None else None,
            )
            try:
                if remaining is not None and remaining <= 0:
                    raise self._timeout(operation)
                result = call(remaining)
                if (
                    call_limit is not None
                    and self.events.clock() - started_at >= call_limit
                ):
                    # 总/步骤超时优先保留运行时异常及其事件分类。
                    self.state.check_active()
                    raise self._timeout(operation)
                return result
            except Exception as error:
                # 取消/运行时终止不能被重试配置重新启动。
                from slothy.core.runtime.state import RunStateError
                from slothy.core.runtime.snapshot import SnapshotError

                if isinstance(error, (RunStateError, SnapshotError)):
                    raise
                on_failure(error)
                self.state.check_active()
                action = self.policy.on_error(FailureContext(
                    operation=operation, error=error, attempt=attempt,
                    tool_name=tool_name, streamed=streamed(),
                    replay_guarded=replay_guarded,
                ))
                # 即使自定义策略放宽类型，也不能重放已交付的流式文本。
                if action is ErrorAction.RETRY and not streamed():
                    if (
                        call_limit is not None
                        and self.events.clock() - started_at >= call_limit
                    ):
                        raise self._timeout(operation) from error
                    self.events.emit(PolicyTriggered(
                        policy="retry", decision="retry",
                        reason=f"{operation} retry {attempt}",
                    ))
                    attempt += 1
                    continue
                if action is ErrorAction.RETURN_ERROR and recover is not None:
                    self.events.emit(PolicyTriggered(
                        policy="safety", decision="return_error",
                        reason="tool failure returned to model",
                    ))
                    return recover(error)
                raise

    def record_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        """仅比较请求与结果的哈希，不让调用 ID 掩盖重复，也不发出原文。"""
        self._round.append(self._result_signature(call, result))

    @staticmethod
    def _result_signature(call: ToolCall, result: ToolResult) -> str:
        return dumps(
            [call.name, call.arguments, result.output, result.is_error],
            ensure_ascii=False, sort_keys=True,
        )

    def validate_round(self, results: list[tuple[ToolCall, ToolResult]]) -> None:
        from slothy.core.runtime.snapshot import SnapshotError

        if self._round != [self._result_signature(call, result)
                           for call, result in results]:
            raise SnapshotError("policy progress differs from committed tool results")

    def finish_round(self, on_committed: Callable[[], None] | None = None) -> None:
        fingerprint = sha256(dumps(self._round).encode("utf-8")).digest()
        self.state.no_progress_rounds = (
            self.state.no_progress_rounds + 1
            if fingerprint == self._previous_round else 1
        )
        self._previous_round = fingerprint
        self._round.clear()
        if on_committed is not None:
            on_committed()
        self.should_terminate()

    @staticmethod
    def _timeout(operation: str) -> Exception:
        kind = LLMTimeoutError if operation == "model" else ToolTimeoutError
        return kind("调用超过策略时限")
