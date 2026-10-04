"""模型调用（LLM 级）事件。

模型模块在发起模型请求和收到响应时发出这些事件。事件只记录请求规模与用量计数，
不记录消息内容、提示词或提供方原始响应。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from slothy.core.context.messages import MessageRole
from slothy.core.model import ModelUsage

from .base import ErrorInfo, RunCheckedError, RunEvent


class ModelCheckedError(RunCheckedError):
    """模型调用失败的分类基类，供提供方适配器继承。"""

    error_code = "model_error"


class LLMTimeoutError(ModelCheckedError, TimeoutError):
    """模型调用超时。

    提供方适配器抛出本异常时，模型模块发出 ``LLMTimeout``；使用其他超时异常
    会被记为 ``unexpected_timeout`` 以便排查未统一的调用方。
    """

    error_code = "llm_timeout"


class TransientModelError(ModelCheckedError):
    """提供方明确判定为可重试的连接、限流或暂时服务故障。"""

    error_code = "model_transient_error"


@dataclass
class ModelEvent(RunEvent):
    """描述一次模型调用的事件，总是发生在某个步骤内。"""

    EVENT_TYPE = "run.model"


@dataclass
class ModelRequestStart(ModelEvent):
    """模型模块已提交请求，正在等待响应。"""

    EVENT_TYPE = "run.model.request_started"

    message_count: int = 0
    tool_count: int = 0


@dataclass
class ModelResponded(ModelEvent):
    """模型已返回响应，``tool_call_count`` 说明下一步是否需要工具。"""

    EVENT_TYPE = "run.model.responded"

    duration_ms: float = 0.0
    text_length: int = 0
    tool_call_count: int = 0
    usage: ModelUsage = field(default_factory=ModelUsage)


@dataclass
class TokenChunk(ModelEvent):
    """模型响应流中的一段增量文本。

    仅当提供方在 ``ModelProvider.generate(..., on_chunk=...)`` 中调用回调时
    产生；不支持流式的提供方不会发出本事件。
    """

    EVENT_TYPE = "run.model.token_chunk"

    index: int = 0
    text: str = ""
    role: MessageRole = MessageRole.ASSISTANT


@dataclass
class ModelError(ModelEvent):
    """一次模型尝试失败；策略决定重试或进入失败终态。"""

    EVENT_TYPE = "run.model.error"

    duration_ms: float = 0.0
    error: ErrorInfo | None = None


@dataclass
class LLMTimeout(ModelEvent):
    """一次模型尝试超时；策略决定重试或进入失败终态。"""

    EVENT_TYPE = "run.model.timeout"

    duration_ms: float = 0.0
    error: ErrorInfo | None = None
