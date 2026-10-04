"""持久化幂等键适配器；未知结果必须审批，不宣称外部副作用原子提交。"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from slothy.core.tools import IdempotencyCheck, VerificationStatus, ToolResult
from slothy.core.tools.replay import (
    IdempotencyConflictError, IdempotencyUncertainError,
)


class SQLiteIdempotencyLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tool_idempotency "
                "(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
                "status TEXT NOT NULL, result TEXT, token TEXT NOT NULL)"
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _check_binding(row, fingerprint):
        if row is not None and row[0] != fingerprint:
            raise IdempotencyConflictError("idempotency key has different arguments")

    def verify(self, key, fingerprint):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fingerprint, status, result FROM tool_idempotency WHERE key=?",
                (key,),
            ).fetchone()
        self._check_binding(row, fingerprint)
        if row is None:
            return IdempotencyCheck(VerificationStatus.NOT_STARTED)
        if row[1] == "completed":
            result = json.loads(row[2])
            return IdempotencyCheck(
                VerificationStatus.COMPLETED, ToolResult(**result),
            )
        return IdempotencyCheck(VerificationStatus.UNKNOWN)

    def claim(self, key, fingerprint, *, approved=False):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT fingerprint, status, result FROM tool_idempotency WHERE key=?",
                (key,),
            ).fetchone()
            self._check_binding(row, fingerprint)
            if row is not None and row[1] == "completed":
                return ToolResult(**json.loads(row[2])), ""
            if row is not None and not approved:
                raise IdempotencyUncertainError("prior execution has an unknown result")
            token = uuid4().hex
            connection.execute(
                "INSERT INTO tool_idempotency VALUES (?, ?, 'executing', NULL, ?) "
                "ON CONFLICT(key) DO UPDATE SET status='executing', result=NULL, "
                "token=excluded.token",
                (key, fingerprint, token),
            )
        return None, token

    def complete(self, key, fingerprint, token, result):
        encoded = json.dumps(
            {"output": result.output, "is_error": result.is_error},
            ensure_ascii=False, allow_nan=False,
        )
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tool_idempotency SET status='completed', result=? "
                "WHERE key=? AND fingerprint=? AND token=? AND status='executing'",
                (encoded, key, fingerprint, token),
            )
            if cursor.rowcount != 1:
                raise IdempotencyConflictError("idempotency reservation has changed")


class KeyedToolExecutor:
    """包装现有受控执行器；键记录不能替代参数校验或执行器授权。"""

    def __init__(self, executor, ledger: SQLiteIdempotencyLedger):
        self.executor, self.ledger = executor, ledger

    def verify_idempotency(self, call, context):
        if not context.idempotency_key or not context.request_fingerprint:
            return IdempotencyCheck(VerificationStatus.UNKNOWN)
        return self.ledger.verify(context.idempotency_key, context.request_fingerprint)

    def execute(self, call, context, on_progress=None):
        if not context.idempotency_key:
            return self.executor.execute(call, context, on_progress)
        cached, token = self.ledger.claim(
            context.idempotency_key, context.request_fingerprint,
            approved=bool(context.approval_id),
        )
        if cached is not None:
            return cached
        # reserve → side effect → completed；崩溃或异常留下未知标记，禁止盲目重放。
        result = self.executor.execute(call, context, on_progress)
        self.ledger.complete(
            context.idempotency_key, context.request_fingerprint, token, result,
        )
        return result
