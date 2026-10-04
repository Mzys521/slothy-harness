"""重建 Runtime 与 SQLite 适配器，验证持久化的快照、幂等标记和审批。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager

from slothy.core.context import InMemoryContext, SummaryStrategy
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import RetryPolicy
from slothy.core.runtime import (
    AgentRunner, RuntimeSnapshot, RunStatus, SnapshotConflictError, SnapshotError,
)
from slothy.core.tools import (
    ApprovalDecision, IdempotencyConflictError, IdempotencyUncertainError,
    ReplaySafety, ToolContext, ToolResult, VerificationStatus,
)
from slothy.infrastructure.app_tools.idempotency import (
    KeyedToolExecutor, SQLiteIdempotencyLedger,
)
from slothy.infrastructure.persistence.runtime_store import SQLiteSnapshotStore


class Crash(BaseException):
    pass


@contextmanager
def connection_to(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class Registry:
    def definitions(self):
        return [{"name": "create"}]

    def get_tool(self, name):
        return SimpleNamespace(
            replay_safety=ReplaySafety.KEYED, execution_version="1",
            timeout_seconds=None,
        )


class Model(ModelProvider):
    def generate(self, messages, **kwargs):
        if messages[-1]["role"] == "tool":
            return ModelResult(text="done")
        return ModelResult(tool_calls=[ToolCall("operation-1", "create", {"value": 7})])


class BusinessExecutor:
    def __init__(self, path, *, crash=False):
        self.path, self.crash = path, crash
        with connection_to(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS effects (value INTEGER)")

    def execute(self, call, context, on_progress=None):
        with connection_to(self.path) as connection:
            connection.execute(
                "INSERT INTO effects VALUES (?)", (call.arguments["value"],),
            )
        if self.crash:
            raise Crash()  # 外部副作用已提交，幂等结果尚未记账。
        return ToolResult(output={"created": call.arguments["value"]})


class RecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runtime.sqlite"
        self.context = ToolContext("persistent-run")

    def effects(self):
        with connection_to(self.path) as connection:
            return connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0]

    def runner(self, *, crash=False, store=None):
        executor = KeyedToolExecutor(
            BusinessExecutor(self.path, crash=crash),
            SQLiteIdempotencyLedger(self.path),
        )
        return AgentRunner(
            Model(), Registry(), executor, policy=RetryPolicy(),
            snapshot_store=store or SQLiteSnapshotStore(self.path),
        )

    def test_completed_receipt_survives_crash_before_runtime_result_commit(self):
        class CrashOnResult(SQLiteSnapshotStore):
            def save(self, snapshot, *, expected_revision):
                records = snapshot.to_dict()["tools"]["records"]
                if any(record["status"] == "completed" for record in records.values()):
                    raise Crash()
                return super().save(snapshot, expected_revision=expected_revision)

        runner = self.runner(store=CrashOnResult(self.path))
        with self.assertRaises(Crash):
            runner.run("create", context=self.context)
        self.assertEqual(self.effects(), 1)
        snapshot = SQLiteSnapshotStore(self.path).load(self.context.run_id)
        record = snapshot.to_dict()["tools"]["records"]["1:operation-1"]
        self.assertEqual(record["status"], "executing")
        restored = self.runner().resume(snapshot, context=self.context)
        self.assertEqual(restored.output, "done")
        self.assertEqual(self.effects(), 1)

    def test_unknown_side_effect_blocks_after_restart_and_can_be_denied(self):
        with self.assertRaises(Crash):
            self.runner(crash=True).run("create", context=self.context)
        store = SQLiteSnapshotStore(self.path)
        waiting = self.runner().resume(
            store.load(self.context.run_id), context=self.context,
        )
        self.assertEqual(waiting.run.status, RunStatus.WAITING_APPROVAL)
        self.assertEqual(waiting.approval.reason, "execution_unknown")
        self.assertEqual(waiting.approval.arguments, {"value": 7})
        self.assertEqual(self.effects(), 1)
        denied = self.runner().resume(
            waiting.snapshot, context=self.context,
            approval=ApprovalDecision(waiting.approval.request_id, False, "human"),
        )
        self.assertEqual(denied.output, "done")
        self.assertEqual(self.effects(), 1)

    def test_unknown_side_effect_requires_explicit_single_attempt_consent(self):
        with self.assertRaises(Crash):
            self.runner(crash=True).run("create", context=self.context)
        store = SQLiteSnapshotStore(self.path)
        waiting = self.runner().resume(
            store.load(self.context.run_id), context=self.context,
        )
        restored = self.runner().resume(
            waiting.snapshot, context=self.context,
            approval=ApprovalDecision(waiting.approval.request_id, True, "human"),
        )
        self.assertEqual(restored.output, "done")
        self.assertEqual(self.effects(), 2)  # 用户明确接受未知执行可能重复的风险。
        records = restored.snapshot.to_dict()["tools"]["records"]
        self.assertEqual(records["1:operation-1"]["attempts"], 2)
        self.assertEqual(len(records["1:operation-1"]["approvals"]), 1)

    def test_sqlite_snapshot_compare_and_swap_is_transactional(self):
        result = self.runner().run("create", context=self.context)
        first, second = SQLiteSnapshotStore(self.path), SQLiteSnapshotStore(self.path)
        saved = first.save(result.snapshot, expected_revision=result.snapshot.revision)
        with self.assertRaises(SnapshotConflictError):
            second.save(result.snapshot, expected_revision=result.snapshot.revision)
        self.assertEqual(second.load(self.context.run_id).revision, saved.revision)
        with self.assertRaises(SnapshotConflictError):
            self.runner().resume(result.snapshot, context=self.context)
        self.assertEqual(self.effects(), 1)

    def test_key_binding_and_reservation_survive_new_adapter(self):
        first = SQLiteIdempotencyLedger(self.path)
        cached, token = first.claim("key", "fingerprint")
        self.assertIsNone(cached)
        second = SQLiteIdempotencyLedger(self.path)
        self.assertEqual(second.verify("key", "fingerprint").status,
                         VerificationStatus.UNKNOWN)
        with self.assertRaises(IdempotencyUncertainError):
            second.claim("key", "fingerprint")
        with self.assertRaises(IdempotencyConflictError):
            second.claim("key", "changed", approved=True)
        first.complete("key", "fingerprint", token, ToolResult(output=42))
        self.assertEqual(second.verify("key", "fingerprint").result.output, 42)

    def test_old_reservation_cannot_complete_new_approved_attempt(self):
        ledger = SQLiteIdempotencyLedger(self.path)
        _, old = ledger.claim("key", "fingerprint")
        _, current = ledger.claim("key", "fingerprint", approved=True)
        with self.assertRaises(IdempotencyConflictError):
            ledger.complete("key", "fingerprint", old, ToolResult(output="old"))
        ledger.complete("key", "fingerprint", current, ToolResult(output="new"))
        self.assertEqual(ledger.verify("key", "fingerprint").result.output, "new")

    def test_snapshot_json_has_no_executable_provider_or_handler_objects(self):
        result = self.runner().run("create", context=self.context)
        restored = RuntimeSnapshot.from_json(result.snapshot.to_json())
        self.assertEqual(restored.to_dict(), result.snapshot.to_dict())
        self.assertNotIn("handler", restored.to_dict())
        with connection_to(self.path) as connection:
            connection.execute(
                "UPDATE runtime_snapshots SET payload='invalid' WHERE run_id=?",
                (self.context.run_id,),
            )
        with self.assertRaises(SnapshotError):
            SQLiteSnapshotStore(self.path).load(self.context.run_id)

    def test_context_snapshot_keeps_compacted_window_and_full_history(self):
        original = InMemoryContext(
            token_budget=100, strategy=SummaryStrategy(lambda *_: "old facts"),
        )
        for number in range(10):
            original.add({"role": "user", "content": f"{number}" * 100})
        original.get_windowed_messages()
        state = original.snapshot_state()
        restored = InMemoryContext(
            token_budget=100, strategy=SummaryStrategy(lambda *_: "old facts"),
        )
        restored.restore_state(state)
        self.assertEqual(restored.get_history(), original.get_history())
        self.assertEqual(restored.snapshot_state(), state)


if __name__ == "__main__":
    unittest.main()
