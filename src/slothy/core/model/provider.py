"""抽象模型提供方契约（核心层）。

基础设施层中的具体提供方（例如 ``MimoProvider``）实现该契约。认证、请求转换、
响应转换和错误映射等提供方特有逻辑保留在这些实现内部，绝不允许泄漏到核心层。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .model_models import ModelResult


class ModelProvider(ABC):
    """所有具体 LLM 提供方共享的抽象契约。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResult:
        """为给定的对话消息生成模型响应。

        参数：
            messages: 提供方中立格式的对话消息，
                每一项通常包含 ``role`` 和 ``content``。
            **kwargs: 可选的生成参数，例如 ``temperature``、
                ``max_tokens`` 或 ``stream``。模型模块的调用入口还会传入
                ``on_chunk``：实现流式响应的提供方应在收到文本增量时调用它，
                以便模型模块发出 ``TokenChunk`` 事件；不支持流式的提供方
                应忽略该参数而不是把它转发给模型服务。
                ``timeout`` 是策略计算的剩余秒数，支持时限的适配器应据此
                配置 I/O 超时；适配器不应自行重试，重试由 Policy 管理。

        返回：
            模型生成的提供方中立的 :class:`ModelResult`。
        """
        ...
