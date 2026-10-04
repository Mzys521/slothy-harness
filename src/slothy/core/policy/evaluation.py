"""工具策略的集成入口；规则实现与判定事件均归策略模块。"""

from slothy.core.events import GuardrailBlocked, PolicyTriggered
from slothy.core.events.emitter import EventEmitter
from slothy.core.model.model_models import ToolCall

from .policy import PolicyEngine, ToolPolicyRequest
from .resilience import Policy


def check_tool_call(
    policy: Policy | PolicyEngine,
    call: ToolCall,
    run_id: str,
    events: EventEmitter,
) -> str | None:
    """允许时返回 None，拦截时返回可安全反馈给模型的错误说明。

    ASK 保持拦截语义，尚不提供审批等待或恢复执行。规则异常原样向外传播。
    """
    decision = policy.decide(
        ToolPolicyRequest(call_id=call.call_id, name=call.name, run_id=run_id)
    )
    if decision.matched:
        events.emit(
            PolicyTriggered(
                policy=decision.policy,
                decision=decision.verdict.value,
                reason=decision.reason,
            )
        )
    if decision.is_allow:
        return None
    events.emit(
        GuardrailBlocked(
            guardrail=decision.policy,
            call_id=call.call_id,
            name=call.name,
            reason=decision.reason,
        )
    )
    if decision.is_ask:
        return "工具调用需要人工确认，当前尚未实现审批流程，已拦截"
    return "工具调用被安全策略拦截"
