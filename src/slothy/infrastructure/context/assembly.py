"""宿主可复用的 Context 组件组装；不导入 Application 或运行循环。"""

from dataclasses import dataclass
import os

from slothy.core.context import LayeredContext, HeuristicTokenEstimator, HybridRetriever

from .channels import SQLiteRetrievalChannel
from .dashscope import DashScopeChatProvider, DashScopeEmbedding, DashScopeReranker, DashScopeSummarizer
from .settings import context_config, retrieval_config
from .sqlite_store import SQLiteContextStore
from .timeout import BoundedInvoker, TimedSummarizer
from .tools import ContextToolExecutor, memory_tools


@dataclass
class ContextComponents:
    store: object
    config: object
    retriever: HybridRetriever
    summarizer: object
    definitions: tuple
    estimator: object
    observer: object = None

    def create_context(self, *, system_prompt="", scope=None, task_state=None, extract_schemas=None):
        return LayeredContext(store=self.store, config=self.config, estimator=self.estimator,
                              system_prompt=system_prompt, scope=scope, task_state=task_state,
                              summarizer=self.summarizer, observer=self.observer, extract_schemas=extract_schemas)

    def create_executor(self, registry, base, *, extract_schemas=None):
        return ContextToolExecutor(registry, base, store=self.store, retriever=self.retriever,
                                   config=self.config, definitions=self.definitions,
                                   estimator=self.estimator, extract_schemas=extract_schemas)


def assemble_context_components(*, path=None, store=None, config=None, retrieval=None,
                                remote=False, summarizer=None, observer=None, estimator=None):
    cfg, rag = config or context_config(), retrieval or retrieval_config()
    store = store if store is not None else SQLiteContextStore(path or os.environ.get("SLOTHY_CONTEXT_DB") or ".slothy/context.sqlite3")
    estimator = estimator or HeuristicTokenEstimator()
    invoker = BoundedInvoker()
    embedding = reranker = None
    if remote:
        # 任意缺失服务不影响本地 BM25/实体通道，显式错误配置则在组装时拒绝。
        if os.environ.get("DASHSCOPE_MODEL"):
            embedding = DashScopeEmbedding()
        if os.environ.get("DASHSCOPE_RERANK_MODEL"):
            reranker = DashScopeReranker()
        if summarizer is None and os.environ.get("DASHSCOPE_CHAT_MODEL"):
            summarizer = DashScopeSummarizer(DashScopeChatProvider(timeout_seconds=cfg.summary_timeout_seconds),
                                             timeout_seconds=cfg.summary_timeout_seconds,
                                             input_token_budget=cfg.summary_input_tokens, estimator=estimator)
    if summarizer is not None:
        summarizer = TimedSummarizer(summarizer, cfg.summary_timeout_seconds, invoker)
    retriever = HybridRetriever(
        vector=SQLiteRetrievalChannel("vector", store, rag, embedding) if embedding else None,
        bm25=SQLiteRetrievalChannel("bm25", store, rag), entity=SQLiteRetrievalChannel("entity", store, rag),
        reranker=reranker, config=rag, invoker=invoker, observer=observer,
    )
    return ContextComponents(store, cfg, retriever, summarizer, memory_tools(cfg, rag), estimator, observer)
