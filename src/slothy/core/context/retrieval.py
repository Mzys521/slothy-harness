"""混合检索契约与融合算法。数据库、向量服务和超时执行器由外层实现。"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from typing import Protocol

from .contracts import ContextError
from .observations import MemoryScope


@dataclass(frozen=True)
class RetrievalConfig:
    candidate_limit: int = 20
    top_k: int = 4
    vector_weight: float = 0.55
    bm25_weight: float = 0.30
    entity_weight: float = 0.15
    time_weight: float = 0.10
    half_life_days: float = 30.0
    vector_timeout_seconds: float = 3.0
    bm25_timeout_seconds: float = 1.0
    entity_timeout_seconds: float = 1.0
    rerank_timeout_seconds: float = 3.0
    min_score: float = 0.0
    query_chars: int = 2048
    document_chars: int = 4096
    scan_limit: int = 10000
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    max_entity_filters: int = 16
    entity_value_chars: int = 256

    def __post_init__(self):
        for name, value in vars(self).items():
            if name in {"candidate_limit", "top_k", "query_chars", "document_chars", "scan_limit", "max_entity_filters", "entity_value_chars"}:
                if type(value) is not int or value < 1:
                    raise ValueError(f"{name} 必须是正整数")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0 or ("timeout" in name or name in {"half_life_days", "bm25_k1"}) and value == 0:
                raise ValueError(f"{name} 无效")
        if self.top_k > self.candidate_limit or self.bm25_b > 1:
            raise ValueError("top_k / bm25_b 超出范围")
        if self.vector_weight + self.bm25_weight + self.entity_weight <= 0:
            raise ValueError("至少一个检索通道权重必须为正")


@dataclass(frozen=True)
class MemoryDocument:
    id: str
    owner_id: str
    text: str
    created_at: str
    source: str = "memory"
    entities: dict[str, str] = field(default_factory=dict)
    vector: tuple[float, ...] = ()
    embedding_model: str = ""


@dataclass(frozen=True)
class SearchHit:
    document: MemoryDocument
    score: float


class RetrievalChannel(Protocol):
    def search(self, query: str, scope: MemoryScope, *, limit: int,
               entities: dict[str, str], timeout_seconds: float) -> list[SearchHit]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str], *, timeout_seconds: float) -> list[tuple[int, float]]: ...


class EmbeddingProvider(Protocol):
    model: str
    def embed(self, texts: list[str], *, timeout_seconds: float) -> list[list[float]]: ...


class MemoryRepository(Protocol):
    def upsert(self, document: MemoryDocument) -> None: ...
    def upsert_many(self, documents: list[MemoryDocument]) -> None: ...
    def recent_completed(self, scope: MemoryScope, *, limit: int = 1) -> list[MemoryDocument]: ...


class DirectInvoker:
    """测试或已实现 I/O 超时的注入对象；生产用外层 BoundedInvoker。"""
    def invoke(self, operation, timeout_seconds):
        return operation()


class HybridRetriever:
    def __init__(self, *, vector=None, bm25=None, entity=None, reranker=None,
                 config=None, invoker=None, observer=None, clock=None):
        self.channels = {"vector": vector, "bm25": bm25, "entity": entity}
        self.config = config or RetrievalConfig()
        self.reranker, self.invoker = reranker, invoker or DirectInvoker()
        self.observer = observer
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_report = None

    def search(self, query, scope, *, entities=None, top_k=None):
        return self.search_with_report(query, scope, entities=entities, top_k=top_k)[0]

    def search_with_report(self, query, scope, *, entities=None, top_k=None):
        """返回本次调用的报告，避免并行 Run 读取共享 last_report 的竞态。"""
        cfg = self.config
        if not isinstance(query, str) or not query.strip() or len(query) > cfg.query_chars:
            raise ContextError("检索查询为空或超过配置长度")
        if not isinstance(scope, MemoryScope):
            raise ContextError("检索必须有宿主范围")
        entities = deepcopy(entities or {})
        if not isinstance(entities, dict) or len(entities) > cfg.max_entity_filters or any(not isinstance(k, str) or not isinstance(v, str) or len(k) > cfg.entity_value_chars or len(v) > cfg.entity_value_chars for k, v in entities.items()):
            raise ContextError("实体过滤必须是字符串映射")
        if top_k is not None and (type(top_k) is not int or not 1 <= top_k <= cfg.top_k):
            raise ContextError("top_k 超过宿主配置")
        candidates, statuses = {}, {}
        for name, channel in self.channels.items():
            if channel is None or getattr(cfg, name + "_weight") == 0:
                statuses[name] = "disabled"
                continue
            timeout = getattr(cfg, name + "_timeout_seconds")
            try:
                hits = self.invoker.invoke(lambda: channel.search(query, scope, limit=cfg.candidate_limit,
                                          entities=entities, timeout_seconds=timeout), timeout)
                if not isinstance(hits, list):
                    raise ContextError("检索通道返回无效候选")
                accepted = []
                for hit in hits[:cfg.candidate_limit]:
                    if not isinstance(hit, SearchHit) or not isinstance(hit.document, MemoryDocument) or not isfinite(hit.score):
                        raise ContextError("检索分数无效")
                    doc = hit.document
                    if doc.owner_id != scope.owner_id or any(doc.entities.get(k) != v for k, v in entities.items()):
                        continue
                    if not doc.id or not isinstance(doc.text, str) or len(doc.text) > cfg.document_chars:
                        continue
                    accepted.append(hit)
                scale = max((abs(h.score) for h in accepted), default=1.0) or 1.0
                for hit in accepted:
                    doc = hit.document
                    key = sha256(" ".join(doc.text.split()).encode("utf-8")).hexdigest()
                    entry = candidates.setdefault(key, {"document": doc, "scores": {}})
                    entry["scores"][name] = max(0.0, hit.score / scale)
                statuses[name] = "ok"
            except TimeoutError:
                statuses[name] = "timeout"
            except Exception:
                statuses[name] = "failed"
        now = self.clock()
        scored = []
        for entry in candidates.values():
            doc = entry["document"]
            try:
                created = datetime.fromisoformat(doc.created_at.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    raise ValueError("missing timezone")
                age = max(0.0, (now - created).total_seconds() / 86400)
                decay = 2 ** (-age / cfg.half_life_days)
            except (ValueError, TypeError):
                decay = 0.0
            score = sum(getattr(cfg, name + "_weight") * value for name, value in entry["scores"].items()) + cfg.time_weight * decay
            if score >= cfg.min_score:
                scored.append((doc, score))
        scored.sort(key=lambda item: (-item[1], item[0].id))
        scored = scored[:cfg.candidate_limit]
        rerank_status = "disabled"
        if self.reranker is not None and scored:
            try:
                order = self.invoker.invoke(lambda: self.reranker.rerank(query, [d.text for d, _ in scored],
                                            timeout_seconds=cfg.rerank_timeout_seconds), cfg.rerank_timeout_seconds)
                if not isinstance(order, list) or len(order) != len(scored) or {i for i, _ in order} != set(range(len(scored))) or any(type(i) is not int or isinstance(s, bool) or not isinstance(s, (int, float)) or not isfinite(s) for i, s in order):
                    raise ContextError("重排结果必须覆盖候选且索引不重复")
                reranked = sorted(order, key=lambda pair: (-pair[1], pair[0]))
                scored = [(scored[i][0], score) for i, score in reranked]
                rerank_status = "ok"
            except TimeoutError:
                rerank_status = "timeout_fallback"
            except Exception:
                rerank_status = "failed_fallback"
        selected = scored[:top_k or cfg.top_k]
        report = {"channels": statuses, "candidate_count": len(scored), "selected_count": len(selected), "reranker": rerank_status}
        self.last_report = deepcopy(report)
        if self.observer is not None:
            try:
                self.observer(deepcopy(report))
            except Exception:
                pass
        memories = [{"id": d.id, "text": d.text, "source": d.source, "created_at": d.created_at,
                     "entities": deepcopy(d.entities), "score": score} for d, score in selected]
        return memories, deepcopy(report)
