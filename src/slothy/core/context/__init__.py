"""分层上下文与公开兼容契约。

LayeredContext 负责 XML Prompt、预算、任务状态、外化 observation、滚动摘要
与已授权记忆投影。旧类委托共享引擎并保留消息布局。Core 只定义存储、检索与
模型能力接口；SDK、数据库、环境配置和调用隔离均由外层实现。
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
from .config import ContextConfig
from .layered import LayeredContext
from .observations import (
    MemoryScope, ObservationRecord, ObservationStore, InMemoryObservationStore,
)
from .task_state import TaskState
from .retrieval import (
    RetrievalConfig, HybridRetriever, MemoryDocument, SearchHit,
    RetrievalChannel, Reranker, EmbeddingProvider, MemoryRepository,
)

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
    "ContextConfig", "LayeredContext", "MemoryScope", "ObservationRecord",
    "ObservationStore", "InMemoryObservationStore", "TaskState",
    "RetrievalConfig", "HybridRetriever", "MemoryDocument", "SearchHit",
    "RetrievalChannel", "Reranker", "EmbeddingProvider", "MemoryRepository",
]
