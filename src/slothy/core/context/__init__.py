"""核心上下文契约。

上下文模块负责一次 Run 内的对话上下文与上下文窗口：消息以提供方中立格式
（``role`` 加 ``content``）流转，窗口按令牌预算裁剪最早的消息，并在裁剪发生时
由上下文模块的 Conversation 发出 ``ContextCompressed`` 事件。

正式 Context 提供原始历史与预算内窗口隔离、可替换计数器、截断和可注入摘要器。
不包含会话持久化或记忆注入；摘要器的具体模型调用由外层实现。
"""

from .estimator import (
    ASCII_CHARACTERS_PER_TOKEN,
    HeuristicTokenEstimator,
    TokenEstimator,
)
from .messages import MessageRole
from .window import (
    DEFAULT_TOKEN_BUDGET,
    PREVIEW_LIMIT,
    CompressionRecord,
    ContextWindow,
    WindowBuild,
)
from .contracts import (
    CompressionStrategy,
    Context,
    ContextBudgetExceededError,
    ContextError,
    Summarizer,
)
from .memory import InMemoryContext
from .strategies import SummaryStrategy, TrimOldestStrategy

__all__ = [
    "ASCII_CHARACTERS_PER_TOKEN",
    "DEFAULT_TOKEN_BUDGET",
    "PREVIEW_LIMIT",
    "CompressionRecord",
    "CompressionStrategy",
    "Context",
    "ContextBudgetExceededError",
    "ContextError",
    "ContextWindow",
    "HeuristicTokenEstimator",
    "InMemoryContext",
    "MessageRole",
    "TokenEstimator",
    "Summarizer",
    "SummaryStrategy",
    "TrimOldestStrategy",
    "WindowBuild",
]
