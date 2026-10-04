"""核心策略契约。

Policy 统一决定运行限制与失败处置；DefaultPolicy、TimeoutPolicy、RetryPolicy 和
SafetyPolicy 可组合注入，PolicySession 执行决定。以下工具判定语义保持兼容。

策略模块负责判断一次工具调用是否允许执行：

- ``ALLOW``：允许，工具模块继续交给执行器。
- ``DENY``：拒绝，工具模块不调用执行器，并向模型返回受控的错误结果。
- ``ASK``：需要人工确认。

当前运行时没有审批等待能力，因此 ``ASK`` 与 ``DENY`` 一样被拦截，判定理由会
说明“尚未实现审批”。真正的人工确认、``WAITING_APPROVAL`` 状态与恢复执行需要
单独设计后再接入；在那之前不要在本模块预先加入空接口。

策略判定不替代执行器自身的参数校验与授权：模型只能提出请求，策略与执行器各自
完成自己那部分检查。
"""

from .policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyVerdict,
    ToolPolicyRequest,
    ToolPolicyRule,
)
from .rules import AllowlistRule, ToolNameRule
from .resilience import (
    DefaultPolicy, ErrorAction, FailureContext, Policy, PolicyLimits,
    PolicySnapshot, RetryPolicy, SafetyPolicy, Termination, TerminationKind,
    TimeoutPolicy,
    WrappedPolicy,
)

__all__ = [
    "AllowlistRule",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyVerdict",
    "ToolNameRule",
    "ToolPolicyRequest",
    "ToolPolicyRule",
    "DefaultPolicy", "ErrorAction", "FailureContext", "Policy", "PolicyLimits",
    "PolicySnapshot", "RetryPolicy", "SafetyPolicy", "Termination",
    "TerminationKind", "TimeoutPolicy",
    "WrappedPolicy",
]
