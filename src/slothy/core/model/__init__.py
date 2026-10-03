"""核心模型契约。

保存厂商无关的模型抽象（``ModelProvider``）以及与之交换的数据模型
（``ModelResult``、``ModelUsage``、``ToolCall``）。核心层定义这些契约；
基础设施层负责实现它们。
"""

from .model_models import ModelResult, ModelUsage, ToolCall
from .provider import ModelProvider

__all__ = [
    "ModelProvider",
    "ModelResult",
    "ModelUsage",
    "ToolCall",
]
