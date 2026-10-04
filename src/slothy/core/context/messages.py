"""对话消息的角色契约（核心层）。

上下文系统维护消息历史与请求窗口，消息以提供方中立格式在核心层流转：具体提供方
负责转换为自己的请求格式。此处只定义角色标识，供模型事件与上下文模块复用。
"""

from enum import Enum


class MessageRole(str, Enum):
    """一条对话消息在模型请求中的角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
