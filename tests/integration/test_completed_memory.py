"""已完成任务记忆：真实 Application/Core/SQLite，模型与服务故障为测试注入。"""

from dataclasses import replace
from json import loads
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

from slothy.application.api import RuntimeAPI
from slothy.application.services import MemoryService, RuntimeService
from slothy.core.context import ContextError, MemoryDocument, MemoryScope, RetrievalConfig
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.runtime import AgentRunner, SnapshotError
from slothy.core.tools import ReplaySafety, ToolRegistry
from slothy.desktop import assemble_desktop
from slothy.infrastructure.app_tools import CalculatorToolExecutor, add_tool
from slothy.infrastructure.context.assembly import assemble_context_components
from slothy.infrastructure.context.sqlite_store import SQLiteContextStore
from slothy.infrastructure.persistence.runtime_store import SQLiteSnapshotStore


def context_data(messages):
    return fromstring("<context>" + "\n".join(m["content"] for m in messages) + "</context>")


class ProbeModel(ModelProvider):
    def __init__(self, respond):
        super().__init__(model="memory-test-chat")
        self.respond, self.calls = respond, 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        return self.respond(context_data(messages), self.calls)


class CompletedMemoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.respond = lambda root, calls: ModelResult(text="最终回答")
        self.models = []
        self.bridge = self.desktop()
        self.store = SQLiteContextStore(self.path / "context.sqlite3")
        self.scope = MemoryScope("local-user", "history", "history")

    def desktop(self):
        def factory():
            model = ProbeModel(lambda root, calls: self.respond(root, calls))
            self.models.append(model)
            return model
        return assemble_desktop(data_dir=self.path, model_factory=factory, remote=False)

    def create(self, text="当前测试问题", profile="quick"):
        response = self.bridge.request("create_task", {"user_input": text, "profile": profile})
        self.assertTrue(response["ok"], response)
        return response["data"]["run_id"]

    def records(self):
        return self.store.documents(self.scope, entities={}, limit=100, timeout_seconds=1)

    def test_input_is_not_indexed_before_or_during_model_call(self):
        question = "CURRENT-TASK-unique-input"
        run_id = self.create(question)
        self.assertEqual(self.records(), [])
        def respond(root, calls):
            self.assertEqual(self.records(), [])
            self.assertEqual(loads(root.findtext("long_term_memory")), [])
            self.assertEqual(loads(root.findtext("working_memory"))["messages"], [])
            self.assertEqual(root.findtext("current_user_input")[1:-1], question)
            found = self.bridge.request("search_memory", {"query": question})
            self.assertEqual(found["data"]["memories"], [])
            return ModelResult(text="独立的最终回答")
        self.respond = respond
        result = self.bridge.request("execute_run", {"run_id": run_id})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["status"], "completed")
        documents = self.records()
        self.assertEqual(len(documents), 2)
        self.assertEqual({d.entities["role"] for d in documents}, {"user", "assistant"})
        self.assertTrue(all(d.entities["run_id"] == run_id and d.source == "completed_run" for d in documents))
        self.assertTrue(any(question in d.text for d in documents))
        self.assertTrue(any("独立的最终回答" in d.text for d in documents))

    def test_previous_completed_question_survives_cross_profile_empty_search(self):
        previous = "请计算 eighteen 加 twenty-three"
        first = self.create(previous)
        self.assertTrue(self.bridge.request("execute_run", {"run_id": first})["ok"])
        current = "我刚刚问了什么？"
        second = self.create(current, "advanced")
        def respond(root, calls):
            history = loads(root.findtext("long_term_memory"))
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["entities"]["run_id"], first)
            self.assertIn(previous, history[0]["text"])
            self.assertNotIn(current, history[0]["text"])
            self.assertEqual(loads(root.findtext("task_state"))["goal"], current)
            self.assertEqual(root.findtext("current_user_input")[1:-1], current)
            self.assertFalse(any(d.entities["run_id"] == second for d in self.records()))
            if calls == 1:
                return ModelResult(tool_calls=[ToolCall("lookup", "search_memory", {"query": "unmatched-query-zzzy"})])
            return ModelResult(text="你上一轮问的是：" + previous)
        self.respond = respond
        result = self.bridge.request("execute_run", {"run_id": second})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["output"], "你上一轮问的是：" + previous)

    def test_failed_run_never_enters_history(self):
        def fail(root, calls):
            raise RuntimeError("private provider failure")
        self.respond = fail
        run_id = self.create()
        result = self.bridge.request("execute_run", {"run_id": run_id})
        self.assertFalse(result["ok"])
        self.assertEqual(self.bridge.request("get_run", {"run_id": run_id})["data"]["status"], "failed")
        self.assertEqual(self.records(), [])

    def test_cancelled_run_never_enters_history(self):
        run_id = self.create()
        def cancel(root, calls):
            self.bridge.request("cancel_run", {"run_id": run_id})
            return ModelResult(text="不能保存的取消前响应")
        self.respond = cancel
        self.assertFalse(self.bridge.request("execute_run", {"run_id": run_id})["ok"])
        self.assertEqual(self.bridge.request("get_run", {"run_id": run_id})["data"]["status"], "cancelled")
        self.assertEqual(self.records(), [])

    def test_paused_run_is_saved_once_only_after_restart_and_resume(self):
        question = "恢复后仍须保存原始提问"
        run_id = self.create(question)
        def pause(root, calls):
            self.bridge.request("interrupt_run", {"run_id": run_id})
            return ModelResult(text="暂不属于历史的响应")
        self.respond = pause
        paused = self.bridge.request("execute_run", {"run_id": run_id})
        self.assertTrue(paused["ok"], paused)
        self.assertEqual(paused["data"]["status"], "suspended")
        self.assertEqual(self.records(), [])
        self.respond = lambda root, calls: ModelResult(text="恢复后完成")
        self.bridge = self.desktop()
        result = self.bridge.request("resume_run", {"run_id": run_id,
            "expected_revision": paused["data"]["snapshot_revision"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["status"], "completed")
        documents = self.records()
        self.assertEqual(len(documents), 2)
        self.assertTrue(any(question in d.text for d in documents))
        saved = {d.id: d for d in documents}
        self.bridge = self.desktop()
        self.bridge.request("workspace", {})
        self.bridge.request("get_run", {"run_id": run_id})
        self.assertEqual({d.id: d for d in self.records()}, saved)

    def test_pending_approval_is_not_history_and_resume_stores_original_input(self):
        components = assemble_context_components(store=self.store, remote=False)
        registry = ToolRegistry()
        registry.register_many((replace(add_tool, replay_safety=ReplaySafety.UNVERIFIABLE), *components.definitions))
        snapshots = SQLiteSnapshotStore(self.path / "approval.sqlite3")
        def factory():
            model = ProbeModel(lambda root, calls: ModelResult(tool_calls=[
                ToolCall("calc", "add", {"a": 1, "b": 2})]) if calls == 1 and not loads(root.findtext("working_memory"))["messages"]
                else ModelResult(text="审批后完成"))
            return AgentRunner(model, registry, components.create_executor(registry, CalculatorToolExecutor(registry)),
                context=components.create_context(), snapshot_store=snapshots)
        def service():
            return RuntimeService(factory, registry, snapshot_store=snapshots,
                                  memory_service=MemoryService(self.store))
        api = RuntimeAPI(service(), actor_id="local-user")
        question = "经审批后再执行计算"
        created = api.create_run({"user_input": question})["data"]
        waiting = api.execute_run({"run_id": created["run_id"]})
        self.assertTrue(waiting["ok"], waiting)
        view = waiting["data"]
        self.assertEqual(view["status"], "waiting_approval")
        self.assertEqual(self.records(), [])
        restored = service()
        restored.register_saved_run(view["run_id"], owner_id="local-user")
        api = RuntimeAPI(restored, actor_id="local-user")
        approved = api.approve_tool({"run_id": view["run_id"], "request_id": view["approval_request_id"],
                                    "expected_revision": view["snapshot_revision"]})
        self.assertTrue(approved["ok"], approved)
        self.assertEqual(self.records(), [])
        result = api.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self.records()), 2)
        self.assertTrue(any(question in d.text for d in self.records()))

    def test_completion_snapshot_failure_prevents_memory_write(self):
        run_id = self.create()
        save = SQLiteSnapshotStore.save
        def fail_completion(store, snapshot, *, expected_revision):
            if snapshot.to_dict()["run"]["status"] == "completed":
                raise SnapshotError("test completion checkpoint failure")
            return save(store, snapshot, expected_revision=expected_revision)
        with patch.object(SQLiteSnapshotStore, "save", fail_completion):
            result = self.bridge.request("execute_run", {"run_id": run_id})
        self.assertEqual(result["error"]["code"], "snapshot_error")
        self.assertEqual(self.records(), [])

    def test_memory_failure_keeps_completed_output_and_reports_sanitized_error(self):
        run_id = self.create()
        with patch.object(SQLiteContextStore, "upsert_many", side_effect=ContextError("private storage detail")):
            result = self.bridge.request("execute_run", {"run_id": run_id})
        self.assertEqual(result["error"]["code"], "memory_error")
        self.assertNotIn("private storage detail", str(result))
        view = self.bridge.request("get_run", {"run_id": run_id})["data"]
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["output"], "最终回答")
        self.assertEqual(view["error_code"], "memory_error")
        self.assertEqual(self.records(), [])

    def test_history_survives_restart_and_uses_only_owned_completed_records(self):
        first = self.create("真正完成的上一轮")
        self.bridge.request("execute_run", {"run_id": first})
        service = MemoryService(self.store)
        self.assertEqual(service.recent_completed(actor_id="foreign"), [])
        self.assertTrue(self.bridge.request("remember", {"id": "manual", "text": "普通手工记忆"})["ok"])
        self.assertFalse(self.bridge.request("remember", {"id": "run:fake", "text": "不能伪造任务历史"})["ok"])
        self.assertFalse(self.bridge.request("remember", {"id": "fake", "text": "不能伪造来源", "source": "completed_run"})["ok"])
        self.bridge = self.desktop()
        def check(root, calls):
            history = loads(root.findtext("long_term_memory"))
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["entities"]["run_id"], first)
            return ModelResult(text="从真实已完成历史读取")
        self.respond = check
        second = self.create("我刚刚问了什么？")
        result = self.bridge.request("execute_run", {"run_id": second})
        self.assertTrue(result["ok"], result)

    def test_long_history_is_segmented_without_loss_and_batch_is_atomic(self):
        service = MemoryService(self.store, config=replace(RetrievalConfig(), document_chars=256))
        run = SimpleNamespace(status="completed", run_id="long-run", output="回答" * 400)
        question = "原问题" * 400
        service.remember_completed_run(run, question, actor_id="local-user")
        documents = self.records()
        self.assertTrue(all(len(d.text) <= 256 for d in documents))
        for role, expected in (("user", question), ("assistant", run.output)):
            parts = sorted((d for d in documents if d.entities["role"] == role), key=lambda d: int(d.entities["offset"]))
            restored = "".join(d.text.split("：\n", 1)[1] for d in parts)
            self.assertEqual(restored, expected)
        count = len(documents)
        service.remember_completed_run(run, question, actor_id="local-user")
        self.assertEqual(len(self.records()), count)
        valid = MemoryDocument("atomic-first", "local-user", "不能保留半条输入", "2026-10-05T00:00:00Z")
        invalid = replace(valid, id="atomic-second", entities={"not_json": object()})
        with self.assertRaises(TypeError):
            self.store.upsert_many([valid, invalid])
        self.assertFalse(any(d.id.startswith("atomic-") for d in self.records()))


if __name__ == "__main__":
    unittest.main()
