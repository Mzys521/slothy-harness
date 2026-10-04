"""可组合的运行策略；配置不携带单次 Run 的可变状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Protocol, runtime_checkable

from slothy.core.events import (
    LLMTimeoutError, ToolTimeoutError, TransientModelError,
)

from .policy import PolicyDecision, PolicyEngine, ToolPolicyRequest, ToolPolicyRule


def _positive(value: float | None, name: str) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not isfinite(value) or value <= 0
    ):
        raise ValueError(f"{name} must be a finite positive number")


def _count(value: int, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _minimum(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


@dataclass(frozen=True)
class PolicyLimits:
    max_steps: int = 8
    deadline_seconds: float | None = None
    step_timeout_seconds: float | None = None
    model_timeout_seconds: float | None = None
    tool_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _count(self.max_steps, "max_steps")
        for name in (
            "deadline_seconds", "step_timeout_seconds",
            "model_timeout_seconds", "tool_timeout_seconds",
        ):
            _positive(getattr(self, name), name)


@dataclass(frozen=True)
class PolicySnapshot:
    """只包含决策所需的状态计数，不暴露 Run、消息或工具结果。"""

    step_number: int = 0
    elapsed_seconds: float = 0.0
    step_elapsed_seconds: float = 0.0
    requested_tool_calls: int = 0
    no_progress_rounds: int = 0


class TerminationKind(str, Enum):
    STEP_LIMIT = "step_limit_reached"
    RUN_TIMEOUT = "run_timeout"
    STEP_TIMEOUT = "step_timeout"
    NO_PROGRESS = "no_progress"


@dataclass(frozen=True)
class Termination:
    kind: TerminationKind
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class FailureContext:
    """一次尝试的失败；attempt 从 1 开始，streamed 表示已交付文本。"""

    operation: str
    error: Exception
    attempt: int = 1
    tool_name: str = ""
    streamed: bool = False
    replay_guarded: bool = False


class ErrorAction(str, Enum):
    RAISE = "raise"
    RETRY = "retry"
    RETURN_ERROR = "return_error"


@runtime_checkable
class Policy(Protocol):
    @property
    def limits(self) -> PolicyLimits: ...

    def should_terminate(self, state: PolicySnapshot) -> Termination | None: ...

    def on_error(self, failure: FailureContext) -> ErrorAction: ...

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision: ...

    def timeout_for(
        self, operation: str, state: PolicySnapshot
    ) -> float | None: ...


@dataclass(frozen=True)
class DefaultPolicy:
    """默认最多 8 轮；异常原样抛出，不隐式重试。"""

    max_steps: int = 8
    tool_policy: PolicyEngine = field(default_factory=PolicyEngine)

    def __post_init__(self) -> None:
        _count(self.max_steps, "max_steps")

    @property
    def limits(self) -> PolicyLimits:
        return PolicyLimits(max_steps=self.max_steps)

    def should_terminate(self, state: PolicySnapshot) -> Termination | None:
        if state.step_number > self.max_steps or (
            state.step_number >= self.max_steps and state.requested_tool_calls
        ):
            return Termination(TerminationKind.STEP_LIMIT)
        return None

    def on_error(self, failure: FailureContext) -> ErrorAction:
        return ErrorAction.RAISE

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        return self.tool_policy.decide(request)

    def timeout_for(
        self, operation: str, state: PolicySnapshot
    ) -> float | None:
        return None


@dataclass(frozen=True)
class WrappedPolicy:
    """包装策略的默认委托；自定义策略也可直接实现 Policy 协议。"""

    base: Policy = field(default_factory=DefaultPolicy)

    @property
    def limits(self) -> PolicyLimits:
        return self.base.limits

    def should_terminate(self, state: PolicySnapshot) -> Termination | None:
        return self.base.should_terminate(state)

    def on_error(self, failure: FailureContext) -> ErrorAction:
        return self.base.on_error(failure)

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        return self.base.decide(request)

    def timeout_for(
        self, operation: str, state: PolicySnapshot
    ) -> float | None:
        return self.base.timeout_for(operation, state)


@dataclass(frozen=True)
class TimeoutPolicy(WrappedPolicy):
    """协作式总/步骤/调用时限；嵌套策略总是采用更短的时限。"""

    timeout_seconds: float | None = None
    step_timeout_seconds: float | None = None
    model_timeout_seconds: float | None = None
    tool_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "timeout_seconds", "step_timeout_seconds",
            "model_timeout_seconds", "tool_timeout_seconds",
        ):
            _positive(getattr(self, name), name)

    @property
    def limits(self) -> PolicyLimits:
        previous = self.base.limits
        return PolicyLimits(
            max_steps=previous.max_steps,
            deadline_seconds=_minimum(
                previous.deadline_seconds, self.timeout_seconds
            ),
            step_timeout_seconds=_minimum(
                previous.step_timeout_seconds, self.step_timeout_seconds
            ),
            model_timeout_seconds=_minimum(
                previous.model_timeout_seconds, self.model_timeout_seconds
            ),
            tool_timeout_seconds=_minimum(
                previous.tool_timeout_seconds, self.tool_timeout_seconds
            ),
        )

    def should_terminate(self, state: PolicySnapshot) -> Termination | None:
        limits = self.limits
        if (
            limits.deadline_seconds is not None
            and state.elapsed_seconds >= limits.deadline_seconds
        ):
            return Termination(
                TerminationKind.RUN_TIMEOUT, limits.deadline_seconds
            )
        if (
            state.step_number and limits.step_timeout_seconds is not None
            and state.step_elapsed_seconds >= limits.step_timeout_seconds
        ):
            return Termination(
                TerminationKind.STEP_TIMEOUT, limits.step_timeout_seconds
            )
        return self.base.should_terminate(state)

    def timeout_for(
        self, operation: str, state: PolicySnapshot
    ) -> float | None:
        limits = self.limits
        total = (
            limits.deadline_seconds - state.elapsed_seconds
            if limits.deadline_seconds is not None else None
        )
        step = (
            limits.step_timeout_seconds - state.step_elapsed_seconds
            if state.step_number and limits.step_timeout_seconds is not None
            else None
        )
        call = (
            limits.model_timeout_seconds if operation == "model"
            else limits.tool_timeout_seconds
        )
        return _minimum(total, step, call, self.base.timeout_for(operation, state))


@dataclass(frozen=True)
class RetryPolicy(WrappedPolicy):
    """有界立即重试；工具仅在显式的幂等允许列表内重试。"""

    max_retries: int = 2
    retryable_errors: tuple[type[Exception], ...] = (
        ConnectionError, LLMTimeoutError, ToolTimeoutError, TransientModelError,
    )
    retry_tools: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _count(self.max_retries, "max_retries", minimum=0)
        if not isinstance(self.retryable_errors, tuple) or any(
            not isinstance(kind, type) or not issubclass(kind, Exception)
            for kind in self.retryable_errors
        ):
            raise ValueError("retryable_errors must be exception classes")
        object.__setattr__(self, "retry_tools", frozenset(self.retry_tools))

    def on_error(self, failure: FailureContext) -> ErrorAction:
        if (
            failure.attempt <= self.max_retries
            and not failure.streamed
            and isinstance(failure.error, self.retryable_errors)
            and (failure.operation == "model" or (
                failure.operation == "tool"
                and (failure.replay_guarded or failure.tool_name in self.retry_tools)
            ))
        ):
            return ErrorAction.RETRY
        return self.base.on_error(failure)


@dataclass(frozen=True)
class SafetyPolicy(WrappedPolicy):
    """安全规则与连续重复工具往返检测；可选择把工具异常反馈给模型。"""

    rules: tuple[ToolPolicyRule, ...] = ()
    no_progress_limit: int | None = 3
    return_tool_errors: bool = False

    def __post_init__(self) -> None:
        if self.no_progress_limit is not None:
            _count(self.no_progress_limit, "no_progress_limit")
        object.__setattr__(self, "rules", tuple(self.rules))

    def should_terminate(self, state: PolicySnapshot) -> Termination | None:
        decision = self.base.should_terminate(state)
        if decision is not None:
            return decision
        if (
            self.no_progress_limit is not None
            and state.no_progress_rounds >= self.no_progress_limit
        ):
            return Termination(TerminationKind.NO_PROGRESS)
        return None

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        decision = PolicyEngine(self.rules).decide(request)
        return decision if decision.matched else self.base.decide(request)

    def on_error(self, failure: FailureContext) -> ErrorAction:
        action = self.base.on_error(failure)
        if (
            action is ErrorAction.RAISE and self.return_tool_errors
            and failure.operation == "tool"
        ):
            return ErrorAction.RETURN_ERROR
        return action


def resolve_policy(
    policy: Policy | PolicyEngine | None, max_steps: int | None
) -> Policy:
    """兼容原 PolicyEngine 和 max_steps 参数，拒绝相互矛盾的配置。"""
    if policy is None or isinstance(policy, PolicyEngine):
        return DefaultPolicy(
            max_steps=8 if max_steps is None else max_steps,
            tool_policy=policy if policy is not None else PolicyEngine(),
        )
    if not isinstance(policy, Policy):
        raise TypeError("policy must implement Policy or be a PolicyEngine")
    _count(policy.limits.max_steps, "max_steps")
    if max_steps is not None and max_steps != policy.limits.max_steps:
        raise ValueError("max_steps conflicts with policy.limits.max_steps")
    return policy
