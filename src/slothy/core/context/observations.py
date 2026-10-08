"""工具 observation 的外化契约及受限投影。Core 不接触 SQLite。"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps, loads
from typing import Protocol

from .contracts import ContextBudgetExceededError, ContextError
from .validation import count_tokens


@dataclass(frozen=True)
class MemoryScope:
    owner_id: str
    session_id: str
    task_id: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v or len(v) > 256 for v in
               (self.owner_id, self.session_id, self.task_id)):
            raise ContextError("记忆范围必须由宿主提供有效标识")


@dataclass(frozen=True)
class ObservationRecord:
    id: str
    scope: MemoryScope
    tool_name: str
    created_at: str
    payload_json: str
    summary: str
    token_count: int
    digest: str


class ObservationStore(Protocol):
    def put(self, record: ObservationRecord) -> None: ...
    def get(self, result_id: str, scope: MemoryScope) -> ObservationRecord | None: ...


class InMemoryObservationStore:
    """纯 Python 的测试/嵌入式实现。生产组装必须注入持久存储。"""

    def __init__(self):
        self._records = {}

    def put(self, record: ObservationRecord) -> None:
        previous = self._records.get(record.id)
        if previous is not None and (previous.digest != record.digest or previous.scope != record.scope):
            raise ContextError("observation 标识冲突")
        if previous is not None:
            return
        self._records[record.id] = record

    def get(self, result_id: str, scope: MemoryScope) -> ObservationRecord | None:
        record = self._records.get(result_id)
        return record if record is not None and record.scope == scope else None


class ObservationProjector:
    def __init__(self, store, config, estimator, *, extract_schemas=None, clock=None):
        self.store, self.config, self.estimator = store, config, estimator
        self.extract_schemas = deepcopy(extract_schemas or {})
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    @staticmethod
    def digest(content):
        return sha256(content.encode("utf-8")).hexdigest()

    def project(self, message, scope, tool_name, *, persist=True):
        content = message["content"]
        try:
            payload = loads(content)
        except (ValueError, TypeError):
            payload = {"output": content, "is_error": False}
        if not isinstance(payload, dict) or "output" not in payload:
            payload = {"output": payload, "is_error": False}
        # 执行器可在 Runtime 工具日志提交之前外化长结果。只接受存储中存在且
        # 范围、工具名、摘要指纹匹配的引用；模型构造的伪引用不能跳过校验。
        proposed = payload.get("output")
        if isinstance(proposed, dict) and proposed.get("externalized") is True:
            record = self.store.get(proposed.get("Result_ID", ""), scope)
            if record is None or record.tool_name != tool_name or record.digest != proposed.get("result_digest"):
                raise ContextError("外化工具结果引用无效")
            verified = {**message, "content": record.payload_json}
            projected, _ = self.project(verified, scope, tool_name, persist=persist)
            return projected, True
        output, is_error = payload.get("output"), payload.get("is_error") is True
        try:
            loads(content)
        except ValueError:
            content = dumps(payload, ensure_ascii=False, allow_nan=False)
        digest = self.digest(content)
        identity = dumps([scope.owner_id, scope.session_id, scope.task_id,
                          tool_name, message["call_id"], digest], ensure_ascii=False)
        result_id = "result_" + sha256(identity.encode("utf-8")).hexdigest()
        status = "error" if is_error else ("empty" if output in (None, "", [], {}) else "ok")
        summary = f"tool={tool_name}; status={status}; Result_ID={result_id}"
        record = ObservationRecord(result_id, scope, tool_name, self.clock(), content,
                                   summary, count_tokens(self.estimator, [message]), digest)
        try:
            if persist:
                self.store.put(record)
        except ContextError:
            raise
        except Exception:
            raise ContextError("工具结果外化失败；不能将原始结果发送给模型") from None
        # Extract Schema 由宿主配置字段路径；模型不能选择任意敏感字段。
        selected = output
        paths = self.extract_schemas.get(tool_name)
        if paths is not None:
            selected = {}
            for path in paths:
                value = output
                for key in path.split("."):
                    value = value.get(key) if isinstance(value, dict) else None
                if value is not None:
                    selected[path] = value
        bounded = {"output": selected, "is_error": is_error,
                   "observation": {"Result_ID": result_id, "status": status,
                                   "digest": digest, "summary": summary}}
        serialized = dumps(bounded, ensure_ascii=False, allow_nan=False)
        truncated = len(serialized) > self.config.observation_chars or count_tokens(
            self.estimator, [{**message, "content": serialized}]) > self.config.observation_tokens
        if truncated:
            preview = dumps(selected, ensure_ascii=False, allow_nan=False)
            bounded["output"] = {"Result_ID": result_id, "context_truncated": True,
                                 "preview": preview[:self.config.observation_chars]}
            low, high = 0, len(bounded["output"]["preview"])
            while low < high:
                middle = (low + high + 1) // 2
                candidate = deepcopy(bounded)
                candidate["output"]["preview"] = preview[:middle]
                text = dumps(candidate, ensure_ascii=False)
                if len(text) <= self.config.observation_chars and count_tokens(self.estimator, [{**message, "content": text}]) <= self.config.observation_tokens:
                    low = middle
                else:
                    high = middle - 1
            bounded["output"]["preview"] = preview[:low]
            serialized = dumps(bounded, ensure_ascii=False)
        if len(serialized) > self.config.observation_chars or count_tokens(self.estimator, [{**message, "content": serialized}]) > self.config.observation_tokens:
            raise ContextBudgetExceededError("observation 预算不能容纳结果引用")
        return {**message, "content": serialized}, truncated

    def compact(self, message):
        value = loads(message["content"])
        observation = value["observation"]
        minimal = {"output": {"Result_ID": observation["Result_ID"], "context_truncated": True},
                   "is_error": value["is_error"], "observation": observation}
        return {**message, "content": dumps(minimal, ensure_ascii=False)}
