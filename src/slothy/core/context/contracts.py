"""正式上下文系统的稳定契约；不依赖运行器、事件或具体模型 SDK。"""

from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from .estimator import TokenEstimator
from .window import CompressionRecord, WindowBuild


class ContextError(ValueError):
    """上下文系统的受控错误。"""

    error_code = "context_error"


class ContextBudgetExceededError(ContextError):
    """保护的消息无法放入预算，不能提交一个明知超限的请求。"""

    error_code = "context_budget_exceeded"


@runtime_checkable
class Context(Protocol):
    """消息写入与模型窗口读取的最小接口。"""

    def add(self, message: dict[str, Any]) -> None:
        """接收一条提供方中立的消息。"""
        ...

    def get_windowed_messages(self) -> list[dict[str, Any]]:
        """返回可发送的窗口副本，压缩、计数和历史管理由实现负责。"""
        ...

    @property
    def last_compression(self) -> CompressionRecord | None:
        """最近一次窗口读取的压缩记录；没有压缩时为 None。"""
        ...


class CompressionStrategy(Protocol):
    """可替换的窗口策略，输出必须符合预算并保留系统与最新工具配对。"""

    def compress(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        token_budget: int,
        estimator: TokenEstimator,
    ) -> WindowBuild:
        ...


# 摘要器由外层注入；第二个参数是摘要输出的令牌预算。
Summarizer = Callable[[list[dict[str, Any]], int], str]
