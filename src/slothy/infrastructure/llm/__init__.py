"""LLM 基础设施适配器。

本包对外暴露上层可以依赖的具体提供方适配器。提供方中立的契约
（``ModelProvider``）与共享数据模型（``ModelResult``、``ModelUsage``、
``ToolCall``）位于核心层的 :mod:`slothy.core.model`；本包为方便使用对它们进行了再导出。

具体提供方必须将其厂商特有的逻辑（认证、请求转换、响应转换、错误映射）保留在
:mod:`providers` 子包内部，绝不允许泄漏到核心层。

稳定的对外接口可以直接从本包导入::

    from slothy.infrastructure.llm import ModelProvider, ModelResult
"""

from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from .providers.mimo_provider import MimoProvider

__all__ = [
    "MimoProvider",
    "ModelProvider",
    "ModelResult",
    "ModelUsage",
    "ToolCall",
]
