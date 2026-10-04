"""状态与策略事件。

这些事件由上下文窗口和策略判定发出：裁剪上下文时发出 ``ContextCompressed``，
每次策略判定发出 ``PolicyTriggered``，被拦截的调用额外发出
``GuardrailBlocked``。事件只记录计数与名称，不记录被裁剪的消息内容或工具参数。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import RunEvent


@dataclass
class ContextCompressed(RunEvent):
    """上下文超出令牌预算，最早的消息被裁剪。"""

    EVENT_TYPE = "run.context.compressed"

    tokens_before: int = 0
    tokens_after: int = 0
    messages_removed: int = 0
    strategy: str = ""
    #: 被移除内容的安全预览（仅文本、长度受限）。
    preview: str = ""
    messages_truncated: int = 0


@dataclass
class PolicyTriggered(RunEvent):
    """一次策略判定命中，``decision`` 说明最终处置。

    只有规则真正介入（``ALLOW`` 以外的判定）时才发出；默认允许不产生本事件。
    """

    EVENT_TYPE = "run.policy.triggered"

    policy: str = ""
    decision: str = ""
    reason: str = ""


@dataclass
class GuardrailBlocked(RunEvent):
    """安全边界拦截了一次调用，执行器未被调用。

    运行器向模型返回受控的错误结果，因此拦截不会中断整次执行。
    """

    EVENT_TYPE = "run.policy.guardrail_blocked"

    guardrail: str = ""
    call_id: str = ""
    name: str = ""
    reason: str = ""
