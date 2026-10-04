"""策略判定契约（核心层）。

策略回答“这次调用是否允许执行”。它不执行工具、不修改参数，也不等待用户；
具体规则由外层或基础设施层提供，核心层只定义判定语义与组合方式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence


class PolicyVerdict(str, Enum):
    """一次策略判定的处置结果。"""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class PolicyDecision:
    """一次策略判定的结果。"""

    verdict: PolicyVerdict = PolicyVerdict.ALLOW
    #: 命中的规则名；没有任何规则介入时为空。
    policy: str = ""
    #: 面向调用方与模型的简短理由，不含参数取值或密钥。
    reason: str = ""

    @property
    def is_allow(self) -> bool:
        """判定是否允许执行。"""
        return self.verdict is PolicyVerdict.ALLOW

    @property
    def is_deny(self) -> bool:
        """判定是否拒绝执行。"""
        return self.verdict is PolicyVerdict.DENY

    @property
    def is_ask(self) -> bool:
        """判定是否要求人工确认。"""
        return self.verdict is PolicyVerdict.ASK

    @property
    def matched(self) -> bool:
        """判定是否有规则介入（非默认允许）。"""
        return self.verdict is not PolicyVerdict.ALLOW


@dataclass(frozen=True)
class ToolPolicyRequest:
    """待判定的工具调用，只包含判定所需的字段。"""

    call_id: str
    name: str
    run_id: str = ""


class ToolPolicyRule(Protocol):
    """针对工具调用的单条策略规则。"""

    @property
    def name(self) -> str:
        """规则名，用于事件与日志。"""
        ...

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        """返回本规则对该调用的判定；不介入时返回 ``ALLOW``。"""
        ...


@dataclass(frozen=True)
class PolicyEngine:
    """按注册顺序评估规则的工具策略引擎。

    第一条非 ``ALLOW`` 判定即生效；没有规则介入时为默认允许。引擎不执行工具，
    也不改变运行状态：工具模块经策略集成入口决定拦截还是继续。
    """

    rules: Sequence[ToolPolicyRule] = field(default_factory=tuple)

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        """返回该工具调用的处置结果。"""
        for rule in self.rules:
            decision = rule.decide(request)
            if decision.is_allow:
                continue
            if decision.policy:
                return decision
            return PolicyDecision(
                verdict=decision.verdict,
                policy=rule.name,
                reason=decision.reason,
            )
        return PolicyDecision()
