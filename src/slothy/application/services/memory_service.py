"""长期记忆的原子写入用例。宿主身份不是模型可传入的工具参数。"""

from datetime import datetime, timezone
from dataclasses import replace
from math import isfinite

from slothy.core.context import MemoryDocument, MemoryScope, ContextError, RetrievalConfig
from slothy.core.context.retrieval import DirectInvoker


COMPLETED_RUN_SOURCE = "completed_run"


class MemoryService:
    def __init__(self, repository, *, embedding=None, retriever=None, config=None, invoker=None):
        self.repository, self.embedding, self.retriever = repository, embedding, retriever
        self.config = config or RetrievalConfig()
        self.invoker = invoker or DirectInvoker()

    def remember(self, document_id, text, *, actor_id, entities=None, source="memory", created_at=None):
        if source == COMPLETED_RUN_SOURCE or isinstance(document_id, str) and document_id.startswith("run:"):
            raise ContextError("任务历史只能在执行完成后由宿主保存")
        document, status = self._document(document_id, text, actor_id=actor_id, entities=entities,
                                          source=source, created_at=created_at)
        self.repository.upsert(document)
        return {"id": document_id, "vector_status": status, "embedding_model": document.embedding_model}

    def _document(self, document_id, text, *, actor_id, entities=None, source="memory", created_at=None,
                  with_embedding=True):
        scope = MemoryScope(actor_id, "memory-ingestion", "memory-ingestion")
        if not isinstance(document_id, str) or not document_id or len(document_id) > 256 or not isinstance(text, str) or not text.strip() or len(text) > self.config.document_chars:
            raise ContextError("长期记忆文本或标识无效，请先进行有来源的分段")
        entities = entities if entities is not None else {}
        if not isinstance(entities, dict) or len(entities) > self.config.max_entity_filters or any(not isinstance(k, str) or not isinstance(v, str) or len(k) > self.config.entity_value_chars or len(v) > self.config.entity_value_chars for k, v in entities.items()) or not isinstance(source, str) or not source or len(source) > self.config.entity_value_chars:
            raise ContextError("记忆来源和实体无效")
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone")
        except (ValueError, AttributeError):
            raise ContextError("记忆时间必须包含时区") from None
        vector, model, status = (), "", "disabled"
        if self.embedding is not None and with_embedding:
            try:
                vector = tuple(self.invoker.invoke(lambda: self.embedding.embed([text], timeout_seconds=self.config.vector_timeout_seconds),
                                                  self.config.vector_timeout_seconds)[0])
                model, status = self.embedding.model, "indexed"
            except Exception:
                # 网络故障仍可写入 BM25/实体索引，之后显式重建向量。
                status = "embedding_fallback"
        return MemoryDocument(document_id, scope.owner_id, text, timestamp, source,
                              dict(entities), vector, model), status

    def remember_completed_run(self, run, user_input, *, actor_id):
        """只在完成快照已提交后调用；输入与最终回答作为同一批历史写入。"""
        if run.status != "completed" or not isinstance(run.output, str) or not isinstance(user_input, str) or not user_input.strip():
            raise ContextError("只有已完成执行的输入与最终回答可以进入任务历史")
        if not isinstance(run.run_id, str) or not run.run_id or len(run.run_id) > 128:
            raise ContextError("任务历史缺少有效执行标识")
        timestamp = datetime.now(timezone.utc).isoformat()
        # 每段保留角色与字符范围；长输入/回答不静默截断，也不冒充独立任务。
        messages = (("user", user_input), ("assistant", run.output))
        documents = []
        for role, content in messages:
            label = "历史用户输入" if role == "user" else "历史最终回答"
            header = f"已完成任务（{run.run_id}）\n{label}：\n"
            size = self.config.document_chars - len(header)
            if size < 1:
                raise ContextError("记忆分段预算无法容纳任务来源")
            for start in range(0, max(1, len(content)), size):
                text = header + content[start:start + size]
                index = len(documents)
                document, _ = self._document(f"run:{run.run_id}:{index:06d}", text,
                    actor_id=actor_id, source=COMPLETED_RUN_SOURCE, created_at=timestamp,
                    with_embedding=False,
                    entities={"run_id": run.run_id, "status": "completed", "role": role,
                              "offset": str(start), "total_chars": str(len(content))})
                documents.append(document)
        if self.embedding is not None:
            try:
                vectors = self.invoker.invoke(lambda: self.embedding.embed([d.text for d in documents],
                    timeout_seconds=self.config.vector_timeout_seconds), self.config.vector_timeout_seconds)
                if not isinstance(vectors, list) or len(vectors) != len(documents) or any(
                    not isinstance(v, (list, tuple)) or not v or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not isfinite(n) for n in v)
                    for v in vectors):
                    raise ContextError("任务历史 embedding 批量结果无效")
                documents = [replace(d, vector=tuple(v), embedding_model=self.embedding.model)
                             for d, v in zip(documents, vectors)]
            except Exception:
                pass  # 一次批量超时即回退；不能按分段重复等待远程服务。
        # 仓储保证整批提交；索引失败不能留下只包含当前输入的半条对话。
        self.repository.upsert_many(documents)

    def recent_completed(self, *, actor_id):
        """加载上一条已完成任务的首段输入；不触发远程检索或 embedding。"""
        scope = MemoryScope(actor_id, "memory-history", "memory-history")
        documents = self.repository.recent_completed(scope, limit=1)
        return [{"id": d.id, "text": d.text, "source": d.source, "created_at": d.created_at,
                 "entities": dict(d.entities)} for d in documents]

    def search(self, query, *, actor_id, entities=None):
        if self.retriever is None:
            raise ContextError("没有配置检索服务")
        return self.retriever.search(query, MemoryScope(actor_id, "memory-query", "memory-query"), entities=entities)
