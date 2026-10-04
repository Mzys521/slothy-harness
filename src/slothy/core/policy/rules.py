"""内置的工具策略规则。

这些规则只做名称匹配，不读取工具参数，因此不会有参数取值进入事件或日志。
调用方按需组合，未配置任何规则时为默认允许。
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase

from .policy import PolicyDecision, PolicyVerdict, ToolPolicyRequest


@dataclass(frozen=True)
class ToolNameRule:
    """按工具名称模式判定，支持 ``*`` 通配符。

    例如 ``ToolNameRule("shell*", PolicyVerdict.DENY)`` 会拒绝所有以 ``shell``
    开头的工具。
    """

    pattern: str
    verdict: PolicyVerdict = PolicyVerdict.ASK
    name: str = "tool_name"
    reason: str = ""

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        """名称匹配时返回配置的处置结果。"""
        if not fnmatchcase(request.name, self.pattern):
            return PolicyDecision()
        return PolicyDecision(
            verdict=self.verdict,
            policy=self.name,
            reason=self.reason or f"工具 {request.name} 命中规则 {self.pattern}",
        )


@dataclass(frozen=True)
class AllowlistRule:
    """只允许名单内的工具；其余一律拒绝。

    这不是权限系统本身：具体执行器仍必须在执行前完成自己的参数校验与授权。
    本规则用于让外层显式声明本次运行允许出现哪些工具。
    """

    allowed: frozenset[str]
    name: str = "allowlist"

    def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
        """名单外返回拒绝。"""
        if request.name in self.allowed:
            return PolicyDecision()
        return PolicyDecision(
            verdict=PolicyVerdict.DENY,
            policy=self.name,
            reason=f"工具 {request.name} 不在允许名单内",
        )
