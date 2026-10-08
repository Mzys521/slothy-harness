"""SQLite 持久记忆。使用参数化 SQL，并在每个查询强制绑定 owner。"""

from contextlib import contextmanager
from hashlib import sha256
from json import dumps, loads
from math import isfinite
from pathlib import Path
import sqlite3
from time import monotonic

from slothy.core.context import ContextError, MemoryScope, MemoryDocument, ObservationRecord, SearchHit
from .lexical import terms


class SQLiteContextStore:
    def __init__(self, path, *, timeout_seconds=5.0):
        self.path, self.timeout_seconds = Path(path), timeout_seconds
        if self.path.name == ":memory:":
            raise ValueError("生产存储需要文件路径；测试可使用临时目录")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            # 某些 Python/SQLite 构建不包含 FTS5；仍可用受限纯 Python BM25 回退。
            try:
                connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS context_memory_search USING fts5(tokens, owner_id UNINDEXED, memory_id UNINDEXED)")
                self.fts_available = True
                rows = connection.execute("SELECT id,owner_id,text FROM context_memories WHERE NOT EXISTS (SELECT 1 FROM context_memory_search f WHERE f.owner_id=context_memories.owner_id AND f.memory_id=context_memories.id)").fetchall()
                for row in rows:
                    connection.execute("INSERT INTO context_memory_search VALUES (?,?,?)",
                                       (" ".join(terms(row["text"])), row["owner_id"], row["id"]))
            except sqlite3.OperationalError:
                self.fts_available = False

    @contextmanager
    def _connect(self, timeout_seconds=None):
        connection = sqlite3.connect(self.path, timeout=timeout_seconds or self.timeout_seconds)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        except sqlite3.Error:
            raise ContextError("上下文存储操作失败") from None
        finally:
            connection.close()

    def put(self, record: ObservationRecord):
        # 摘要视图之外的原始文本只落在此表，不进入 Context 快照。
        try:
            payload = loads(record.payload_json)
        except (ValueError, TypeError):
            payload = {"output": record.payload_json, "is_error": False}
        encoded = record.payload_json
        if sha256(encoded.encode("utf-8")).hexdigest() != record.digest:
            raise ContextError("observation 原文与摘要指纹不符")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT owner_id,session_id,task_id,digest FROM context_observations WHERE id=?", (record.id,)).fetchone()
            scope = (record.scope.owner_id, record.scope.session_id, record.scope.task_id)
            if previous is not None:
                if tuple(previous) != (*scope, record.digest):
                    raise ContextError("observation 标识或范围冲突")
                return
            connection.execute("INSERT INTO context_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (record.id, *scope, record.tool_name, record.created_at, encoded,
                                record.summary, record.token_count, record.digest))

    def get(self, result_id, scope):
        if not isinstance(scope, MemoryScope):
            raise ContextError("读取结果必须绑定宿主范围")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM context_observations WHERE id=? AND owner_id=? AND session_id=? AND task_id=?",
                                     (result_id, scope.owner_id, scope.session_id, scope.task_id)).fetchone()
        if row is None:
            return None
        if sha256(row["payload_json"].encode("utf-8")).hexdigest() != row["digest"]:
            raise ContextError("observation 存储完整性校验失败")
        return ObservationRecord(row["id"], scope, row["tool_name"], row["created_at"], row["payload_json"], row["summary"], row["token_count"], row["digest"])

    def upsert(self, document: MemoryDocument):
        self.upsert_many([document])

    def upsert_many(self, documents):
        for document in documents:
            if not isinstance(document, MemoryDocument) or not document.owner_id or not document.id or not document.text:
                raise ContextError("长期记忆记录无效")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in document.vector):
                raise ContextError("向量必须为有限数字")
        with self._connect() as connection:
            for document in documents:
                connection.execute("INSERT INTO context_memories VALUES (?,?,?,?,?,?,?,?) "
                                   "ON CONFLICT(owner_id,id) DO UPDATE SET text=excluded.text,created_at=excluded.created_at,source=excluded.source,entities_json=excluded.entities_json,vector_json=excluded.vector_json,embedding_model=excluded.embedding_model",
                                   (document.id, document.owner_id, document.text, document.created_at,
                                    document.source, dumps(document.entities, ensure_ascii=False, allow_nan=False),
                                   dumps(document.vector, allow_nan=False), document.embedding_model))
                if self.fts_available:
                    connection.execute("DELETE FROM context_memory_search WHERE owner_id=? AND memory_id=?", (document.owner_id, document.id))
                    connection.execute("INSERT INTO context_memory_search VALUES (?,?,?)", (" ".join(terms(document.text)), document.owner_id, document.id))

    def recent_completed(self, scope, *, limit=1):
        if not isinstance(scope, MemoryScope) or type(limit) is not int or not 1 <= limit <= 4:
            raise ContextError("读取任务历史必须绑定宿主范围和有效上限")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM context_memories WHERE owner_id=? AND source='completed_run' "
                "AND json_extract(entities_json,'$.status')='completed' "
                "AND json_extract(entities_json,'$.role')='user' "
                "AND json_extract(entities_json,'$.offset')='0' ORDER BY created_at DESC,id DESC LIMIT ?",
                (scope.owner_id, limit)).fetchall()
        return [MemoryDocument(row["id"], row["owner_id"], row["text"], row["created_at"], row["source"],
                               loads(row["entities_json"]), tuple(loads(row["vector_json"])), row["embedding_model"]) for row in rows]

    def lexical_search(self, query, scope, *, entities, limit, timeout_seconds):
        words = sorted(set(terms(query)))
        if not words:
            return []
        match = " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
        with self._connect(timeout_seconds) as connection:
            deadline = monotonic() + timeout_seconds
            connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            clauses, parameters = ["context_memory_search MATCH ?", "m.owner_id=?"], [match, scope.owner_id]
            for key, value in entities.items():
                clauses.append("EXISTS (SELECT 1 FROM json_each(m.entities_json) WHERE key=? AND value=?)")
                parameters.extend((key, value))
            parameters.append(limit)
            rows = connection.execute("SELECT m.*, -bm25(context_memory_search) AS score FROM context_memory_search "
                                      "JOIN context_memories m ON m.owner_id=context_memory_search.owner_id AND m.id=context_memory_search.memory_id WHERE " +
                                      " AND ".join(clauses) + " ORDER BY score DESC,m.id LIMIT ?", parameters).fetchall()
        return [SearchHit(MemoryDocument(row["id"], row["owner_id"], row["text"], row["created_at"], row["source"],
                                        loads(row["entities_json"]), tuple(loads(row["vector_json"])), row["embedding_model"]), row["score"]) for row in rows]

    def documents(self, scope, *, entities, limit, timeout_seconds):
        with self._connect(timeout_seconds) as connection:
            # 扫描上限由配置约束；租户边界先在 SQL 中应用，实体条件在 LIMIT 前应用。
            clauses, parameters = ["owner_id=?"], [scope.owner_id]
            for key, value in entities.items():
                clauses.append("EXISTS (SELECT 1 FROM json_each(context_memories.entities_json) WHERE key=? AND value=?)")
                parameters.extend((key, value))
            parameters.append(limit)
            rows = connection.execute("SELECT * FROM context_memories WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC,id LIMIT ?", parameters).fetchall()
        return [MemoryDocument(row["id"], row["owner_id"], row["text"], row["created_at"], row["source"],
                               loads(row["entities_json"]), tuple(loads(row["vector_json"])), row["embedding_model"]) for row in rows]
