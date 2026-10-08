"""SQLite、工具 RAG、Application 与同一 Runner 的集成；模型都是替身。"""

from dataclasses import replace
from json import dumps, loads
from pathlib import Path
import tempfile
from threading import Event
import unittest
from xml.etree.ElementTree import fromstring

from pydantic import BaseModel, ConfigDict

from slothy.application.api import MemoryAPI, RuntimeAPI
from slothy.application.services import MemoryService, RuntimeService
from slothy.core.context import ContextConfig, ContextError, MemoryScope, RetrievalConfig
from slothy.core.events import EventBus, ToolCallEnd
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import DefaultPolicy, SafetyPolicy, PolicyVerdict, ToolNameRule
from slothy.core.runtime import AgentRunner, Run, RunStatus
from slothy.core.tools import ToolContext, ToolDefinition, ToolExecutor, ToolRegistry, ToolResult, ReplaySafety
from slothy.infrastructure.context.assembly import assemble_context_components
from slothy.infrastructure.context.timeout import BoundedInvoker
from slothy.infrastructure.persistence.runtime_store import SQLiteSnapshotStore
from slothy.main import assemble_context_demo, demo_summarizer


LONG_OUTPUT = "长结果" * 10000


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def large_result():
    return {"records": LONG_OUTPUT}


def root(messages):
    return fromstring("<context>" + "\n".join(m["content"] for m in messages) + "</context>")


class LargeExecutor(ToolExecutor):
    def __init__(self):
        self.calls = 0

    def execute(self, call, context, on_progress=None):
        self.calls += 1
        return ToolResult(large_result())


class ScriptedModel(ModelProvider):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests, self.options = [], []

    def generate(self, messages, **kwargs):
        self.requests.append(messages)
        self.options.append(kwargs)
        return next(self.responses)


class ContextRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.components = assemble_context_components(path=self.path / "context.sqlite3", remote=False,
                        config=ContextConfig.for_input_budget(8192), summarizer=demo_summarizer)
        self.registry = ToolRegistry()
        self.registry.register(ToolDefinition("large", "读取长结果", NoArgs.model_json_schema(), NoArgs,
                                             large_result, replay_safety=ReplaySafety.IDEMPOTENT))
        self.registry.register_many(self.components.definitions)
        self.executor = LargeExecutor()
        self.snapshots = SQLiteSnapshotStore(self.path / "runs.sqlite3")
        self.scope = MemoryScope("owner", "run", "run")
        self.tool_context = ToolContext("run", {"actor_id": "owner"})

    def runner(self, model):
        context = self.components.create_context()
        runner = AgentRunner(model, self.registry, self.components.create_executor(self.registry, self.executor),
                             context=context, policy=DefaultPolicy(20), snapshot_store=self.snapshots)
        return runner, context

    def test_long_result_not_in_context_or_tool_journal_and_paging_is_scoped(self):
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("call", "large", {})]), ModelResult(text="完成")])
        runner, context = self.runner(model)
        result = runner.run("查询", context=self.tool_context)
        snapshot = result.snapshot.to_dict()
        self.assertNotIn(LONG_OUTPUT, dumps(snapshot, ensure_ascii=False))
        saved_result = snapshot["tools"]["records"][0]["result"] if isinstance(snapshot["tools"]["records"], list) else next(iter(snapshot["tools"]["records"].values()))["result"]
        reference = saved_result["output"]["Result_ID"]
        record = self.components.store.get(reference, self.scope)
        self.assertEqual(loads(record.payload_json)["output"]["records"], LONG_OUTPUT)
        executor = self.components.create_executor(self.registry, self.executor)
        page = executor.execute(ToolCall("page", "get_result", {"result_id": reference, "max_chars": 100}), self.tool_context)
        self.assertEqual(len(page.output["data"]), 100)
        self.assertEqual(page.output["next_offset"], 100)
        other = executor.execute(ToolCall("page", "get_result", {"result_id": reference}), ToolContext("run", {"actor_id": "other"}))
        self.assertTrue(other.is_error)
        self.assertEqual(other.output["code"], "result_not_found")
        for messages, options in zip(model.requests, model.options):
            self.assertLessEqual(context.estimate_request_tokens(messages), 8192)
            self.assertEqual(options["max_tokens"], context.config.output_reserve)

    def test_rag_mounted_as_tool_and_bm25_entity_results_enter_untrusted_layer(self):
        service = MemoryService(self.components.store, retriever=self.components.retriever)
        service.remember("order", "订单 A-123 状态为待支付。", actor_id="owner", entities={"order": "A-123"}, source="orders")
        service.remember("foreign", "订单 A-123 私有内容。", actor_id="other", entities={"order": "A-123"})
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("search", "search_memory", {"query": "A-123", "entities": {"order": "A-123"}})]),
                               ModelResult(text="已查询")])
        runner, context = self.runner(model)
        runner.run("订单状态", context=self.tool_context)
        memories = loads(root(model.requests[-1]).findtext("long_term_memory"))
        self.assertEqual([item["id"] for item in memories], ["order"])
        self.assertEqual(memories[0]["source"], "orders")
        self.assertNotIn("私有内容", dumps(model.requests[-1], ensure_ascii=False))
        self.assertEqual(self.components.retriever.last_report["channels"]["bm25"], "ok")

    def test_rag_long_evidence_is_externalized_but_topk_still_available(self):
        MemoryService(self.components.store).remember("long-doc", "订单 A-123。" * 300, actor_id="owner")
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("search", "search_memory", {"query": "A-123"})]), ModelResult(text="完成")])
        runner, context = self.runner(model)
        runner.run("查询", context=self.tool_context)
        self.assertEqual(loads(root(model.requests[-1]).findtext("long_term_memory"))[0]["id"], "long-doc")

    def test_parameter_and_policy_blocks_happen_before_retrieval(self):
        executor = self.components.create_executor(self.registry, self.executor)
        for arguments in ({"query": "订单", "owner_id": "other"}, {"query": "订单", "top_k": 500},
                          {"query": "q" * 5000}, {"query": "订单", "top_k": True},
                          {"query": "订单", "entities": {str(i): "value" for i in range(17)}},
                          {"query": "订单", "entities": {"order": "x" * 257}}):
            self.assertTrue(executor.execute(ToolCall("search", "search_memory", arguments), self.tool_context).is_error)
        self.assertIsNone(self.components.retriever.last_report)
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("search", "search_memory", {"query": "订单"})]), ModelResult(text="拒绝")])
        runner, context = self.runner(model)
        runner.policy = SafetyPolicy(base=DefaultPolicy(20), rules=(ToolNameRule("search_memory", PolicyVerdict.DENY, "禁止检索"),))
        runner.run("查询", context=self.tool_context)
        self.assertIsNone(self.components.retriever.last_report)

    def test_failed_retrieval_is_error_and_clears_previous_evidence(self):
        from slothy.core.context import MemoryDocument, SearchHit

        class OneSuccessfulLookup:
            calls = 0

            def search(self, query, scope, **kwargs):
                self.calls += 1
                if self.calls > 1:
                    raise TimeoutError("temporary retrieval failure")
                return [SearchHit(MemoryDocument("evidence", scope.owner_id, "旧证据",
                                 "2026-10-05T00:00:00+00:00"), 1.0)]

        self.components.retriever.channels.update(bm25=OneSuccessfulLookup(), entity=None)
        model = ScriptedModel([
            ModelResult(tool_calls=[ToolCall("first", "search_memory", {"query": "订单"})]),
            ModelResult(tool_calls=[ToolCall("second", "search_memory", {"query": "新状态"})]),
            ModelResult(text="检索暂时不可用"),
        ])
        runner, context = self.runner(model)
        runner.run("查询", context=self.tool_context)
        self.assertEqual(loads(root(model.requests[1]).findtext("long_term_memory"))[0]["id"], "evidence")
        self.assertEqual(loads(root(model.requests[2]).findtext("long_term_memory")), [])
        tools = [m for m in context.get_history() if m["role"] == "tool"]
        view = loads(tools[-1]["content"])
        record = self.components.store.get(view["observation"]["Result_ID"], self.scope)
        result = loads(record.payload_json)
        self.assertTrue(result["is_error"])
        self.assertEqual(result["output"]["code"], "retrieval_unavailable")
        self.assertEqual(result["output"]["retrieval"]["channels"]["bm25"], "timeout")

    def test_resume_after_tool_commit_uses_saved_reference_without_reexecution(self):
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("call", "large", {})])])
        runner, context = self.runner(model)
        runtime, bus = Run("run", 20), EventBus()
        bus.subscribe(ToolCallEnd, lambda event: runtime.interrupt())
        paused = runner.run("查询", context=self.tool_context, runtime=runtime, events=bus)
        self.assertEqual(paused.run.status, RunStatus.SUSPENDED)
        self.assertEqual(self.executor.calls, 1)
        new_model = ScriptedModel([ModelResult(text="已恢复")])
        new_runner, new_context = self.runner(new_model)
        resumed = new_runner.resume(paused.snapshot, context=self.tool_context)
        self.assertEqual(resumed.output, "已恢复")
        self.assertEqual(self.executor.calls, 1)
        self.assertNotIn(LONG_OUTPUT, dumps(resumed.snapshot.to_dict(), ensure_ascii=False))

    def test_application_can_run_new_context_without_api_signature_changes(self):
        def factory():
            return self.runner(ScriptedModel([ModelResult(text="应用完成")]))[0]
        api = RuntimeAPI(RuntimeService(factory, self.registry, snapshot_store=self.snapshots), actor_id="owner")
        created = api.create_run({"user_input": "任务"})["data"]
        result = api.execute_run({"run_id": created["run_id"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["output"], "应用完成")

    def test_new_offline_demo_runs_long_task_below_8k_for_summary_and_fallback(self):
        for summarizer in (None, demo_summarizer):
            assembly = assemble_context_demo(context_db=self.path / "demo.sqlite3", summarizer=summarizer)
            created = assembly.api.create_run({"user_input": "长任务"})["data"]
            result = assembly.api.execute_run({"run_id": created["run_id"]})
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["data"]["status"], "completed")
            self.assertLessEqual(max(assembly.models[0].request_tokens), 8192)
            self.assertTrue(assembly.contexts[0].snapshot_state()["archives"])

    def test_timeout_invoker_falls_back_and_does_not_leak_unbounded_threads(self):
        release = Event()
        invoker = BoundedInvoker(capacity=1)
        try:
            with self.assertRaises(TimeoutError):
                invoker.invoke(lambda: release.wait(), .01)
            with self.assertRaises(TimeoutError):
                invoker.invoke(lambda: "no slot", .01)
        finally:
            release.set()

    def test_paging_cursor_tracks_actual_bounded_content(self):
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("call", "large", {})]), ModelResult(text="完成")])
        runner, context = self.runner(model)
        runner.run("任务", context=self.tool_context)
        reference = loads(context.get_history()[-2]["content"])["observation"]["Result_ID"]
        executor = self.components.create_executor(self.registry, self.executor)
        page = executor.execute(ToolCall("page", "get_result", {"result_id": reference, "max_chars": 4096}), self.tool_context)
        self.assertIn("data", page.output)
        self.assertGreater(len(page.output["data"]), 0)
        self.assertLess(len(page.output["data"]), 4096)
        self.assertEqual(page.output["next_offset"], len(page.output["data"]))
        next_page = executor.execute(ToolCall("next", "get_result", {"result_id": reference, "offset": page.output["next_offset"]}), self.tool_context)
        record = self.components.store.get(reference, self.scope)
        joined = page.output["data"] + next_page.output["data"]
        self.assertEqual(joined, record.payload_json[:len(joined)])

    def test_memory_api_binds_actor_and_has_atomic_json_results(self):
        api = MemoryAPI(MemoryService(self.components.store, retriever=self.components.retriever), actor_id="owner")
        rejected = api.remember({"id": "m", "text": "data", "actor_id": "other"})
        self.assertFalse(rejected["ok"])
        self.assertTrue(api.remember({"id": "m", "text": "订单 A-123"})["ok"])
        result = api.search({"query": "A-123"})
        self.assertEqual(result["data"]["memories"][0]["id"], "m")
        other = MemoryAPI(MemoryService(self.components.store, retriever=self.components.retriever), actor_id="other")
        self.assertEqual(other.search({"query": "A-123"})["data"]["memories"], [])

    def test_fts_retrieval_does_not_lose_older_keyword_match_to_scan_limit(self):
        if not self.components.store.fts_available:
            self.skipTest("SQLite 构建没有 FTS5，使用有界扫描回退")
        service = MemoryService(self.components.store)
        service.remember("older", "订单 OLD-123", actor_id="owner", created_at="2025-01-01T00:00:00+00:00")
        service.remember("recent", "天气", actor_id="owner")
        cfg = replace(RetrievalConfig(), scan_limit=1)
        from slothy.infrastructure.context.channels import SQLiteRetrievalChannel
        hits = SQLiteRetrievalChannel("bm25", self.components.store, cfg).search("OLD-123", self.scope, limit=20, entities={}, timeout_seconds=1)
        self.assertEqual(hits[0].document.id, "older")

    def test_corrupted_sqlite_payload_is_rejected(self):
        import sqlite3
        model = ScriptedModel([ModelResult(tool_calls=[ToolCall("call", "large", {})]), ModelResult(text="完成")])
        runner, context = self.runner(model)
        runner.run("任务", context=self.tool_context)
        reference = loads(context.get_history()[-2]["content"])["observation"]["Result_ID"]
        from contextlib import closing
        with closing(sqlite3.connect(self.path / "context.sqlite3")) as connection:
            with connection:
                connection.execute("UPDATE context_observations SET payload_json=? WHERE id=?", ('{"output":"tampered"}', reference))
        with self.assertRaisesRegex(ContextError, "完整性"):
            self.components.store.get(reference, self.scope)


if __name__ == "__main__":
    unittest.main()
