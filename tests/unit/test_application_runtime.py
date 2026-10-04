"""Application 原子用例、JSON 边界及恢复控制；无 SDK、网络或真实等待。"""

import ast
import json
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from slothy.application.api import RuntimeAPI
from slothy.application.services import RuntimeService
from slothy.core.context import InMemoryContext
from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from slothy.core.policy import DefaultPolicy
from slothy.core.runtime import AgentRunner, InMemorySnapshotStore
from slothy.core.tools import ReplaySafety, ToolResult


class Registry:
    def __init__(self, safety=ReplaySafety.IDEMPOTENT):
        self.safety = safety

    def definitions(self):
        return [{"name": "work", "description": "测试工具", "parameters": {
            "type": "object", "properties": {"value": {"type": "integer"}},
        }}]

    def get_tool(self, name):
        return SimpleNamespace(
            replay_safety=self.safety, execution_version="1", timeout_seconds=None,
        )


class Model(ModelProvider):
    def __init__(self):
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        if messages[-1]["role"] == "tool":
            if kwargs.get("on_chunk"):
                kwargs["on_chunk"]("完成")
            return ModelResult(text="完成", usage=ModelUsage(total_tokens=2))
        return ModelResult(tool_calls=[ToolCall("call-1", "work", {"value": 1})])


class Executor:
    def __init__(self):
        self.calls = []

    def execute(self, call, context, on_progress=None):
        self.calls.append((call, context))
        return ToolResult(output=42)


class ApplicationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemorySnapshotStore()
        self.registry = Registry()
        self.executor = Executor()
        self.runners = []
        self.model_factory = Model
        self.service = self.make_service()
        self.api = RuntimeAPI(self.service, actor_id="local-user")

    def make_service(self, *, capacity=1000):
        def factory():
            runner = AgentRunner(
                self.model_factory(), self.registry, self.executor,
                context=InMemoryContext(), policy=DefaultPolicy(), snapshot_store=self.store,
            )
            self.runners.append(runner)
            return runner
        return RuntimeService(factory, self.registry, snapshot_store=self.store, event_capacity=capacity)

    def created(self, api=None):
        response = (api or self.api).create_run({"user_input": "测试"})
        self.assertTrue(response["ok"], response)
        return response["data"]

    def run_payload(self, created):
        return {"run_id": created["run_id"]}

    def waiting(self):
        self.registry.safety = ReplaySafety.UNVERIFIABLE
        created = self.created()
        response = self.api.execute_run(self.run_payload(created))
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["data"]["status"], "waiting_approval")
        return response["data"]

    def approval_payload(self, view):
        return {
            "run_id": view["run_id"], "request_id": view["approval_request_id"],
            "expected_revision": view["snapshot_revision"],
        }

    def test_create_and_query_do_not_execute(self):
        view = self.created()
        self.assertEqual(view["status"], "idle")
        self.assertEqual(self.runners[0].model.requests, [])
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.api.get_run(self.run_payload(view))["data"]["step_count"], 0)
        self.assertEqual(len(self.api.list_runs()["data"]), 1)

    def test_execution_returns_json_dtos_and_controlled_catalog(self):
        view = self.created()
        result = self.api.start_run(self.run_payload(view))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(result["data"]["output"], "完成")
        self.assertFalse(result["data"]["busy"])
        catalog = self.api.list_tools()
        self.assertEqual(catalog["data"][0]["replay_safety"], "idempotent")
        self.assertNotIn("handler", json.dumps(catalog))
        self.assertNotIn("context", result["data"])
        self.assertNotIn("snapshot", result["data"])
        json.dumps(result, allow_nan=False)
        self.assertEqual(self.executor.calls[0][1].metadata, {"actor_id": "local-user"})

    def test_request_validation_rejects_unknown_fields_and_boolean_integers(self):
        for payload in (None, {}, {"user_input": " "}, {"user_input": "测试", "actor_id": "model"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.api.create_run(payload)["error"]["code"], "invalid_request")
        self.assertEqual(self.api.list_runs({"limit": True})["error"]["code"], "invalid_request")
        self.assertEqual(self.api.list_tools({"extra": 1})["error"]["code"], "invalid_request")

    def test_each_run_has_a_separate_context_and_runner(self):
        first, second = self.created(), self.created()
        self.api.execute_run(self.run_payload(first))
        self.api.execute_run(self.run_payload(second))
        self.assertIsNot(self.runners[0], self.runners[1])
        self.assertIsNot(self.runners[0].context, self.runners[1].context)
        self.assertEqual(len(self.runners[1].model.requests[0]), 1)

    def test_reusing_a_context_is_rejected(self):
        runner = AgentRunner(Model(), self.registry, self.executor, context=InMemoryContext())
        api = RuntimeAPI(RuntimeService(lambda: runner, self.registry), actor_id="user")
        self.created(api)
        self.assertEqual(api.create_run({"user_input": "again"})["error"]["code"], "invalid_configuration")

    def test_owner_is_bound_by_host_and_not_exposed_as_client_override(self):
        view = self.waiting()
        other = RuntimeAPI(self.service, actor_id="other-user")
        self.assertEqual(other.list_runs()["data"], [])
        for operation in (other.get_run, other.cancel_run, other.get_events, other.get_approval):
            self.assertEqual(operation(self.run_payload(view))["error"]["code"], "run_not_found")
        self.assertEqual(other.approve_tool(self.approval_payload(view))["error"]["code"], "run_not_found")
        tampered = self.approval_payload(view) | {"actor": "human"}
        self.assertEqual(self.api.approve_tool(tampered)["error"]["code"], "invalid_request")

    def test_approval_and_resume_are_separate_atomic_operations(self):
        view = self.waiting()
        self.assertEqual(self.executor.calls, [])
        approval = self.api.get_approval(self.run_payload(view))
        self.assertEqual(approval["data"]["arguments"], {"value": 1})
        result = self.api.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})
        self.assertEqual(result["error"]["code"], "approval_required")
        approved = self.api.approve_tool(self.approval_payload(view))
        self.assertTrue(approved["ok"], approved)
        self.assertEqual(approved["data"]["actor_id"], "local-user")
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.api.get_run(self.run_payload(view))["data"]["approval_decision"], "approved")
        result = self.api.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(result["data"]["generation"], 1)
        self.assertEqual(len(self.executor.calls), 1)
        self.assertTrue(self.executor.calls[0][1].approval_id)

    def test_rejection_is_fed_to_model_and_never_executes_tool(self):
        view = self.waiting()
        self.assertTrue(self.api.reject_tool(self.approval_payload(view))["ok"])
        self.assertEqual(self.executor.calls, [])
        result = self.api.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.executor.calls, [])
        tool_message = self.runners[0].model.requests[-1][-1]
        self.assertTrue(json.loads(tool_message["content"])["is_error"])

    def test_duplicate_and_stale_approval_cannot_grant_an_extra_attempt(self):
        view = self.waiting()
        payload = self.approval_payload(view)
        self.assertEqual(self.api.approve_tool(payload | {"expected_revision": 1})["error"]["code"], "snapshot_conflict")
        self.assertEqual(self.api.approve_tool(payload | {"request_id": "old"})["error"]["code"], "approval_conflict")
        self.assertTrue(self.api.approve_tool(payload)["ok"])
        self.assertEqual(self.api.reject_tool(payload)["error"]["code"], "approval_already_decided")
        self.assertEqual(self.executor.calls, [])

    def test_get_approval_returns_an_isolated_copy(self):
        view = self.waiting()
        response = self.api.get_approval(self.run_payload(view))
        response["data"]["arguments"]["value"] = 100
        self.assertEqual(self.api.get_approval(self.run_payload(view))["data"]["arguments"]["value"], 1)

    def test_cancel_before_execution_is_terminal(self):
        view = self.created()
        events = []
        self.api.subscribe_events(self.run_payload(view), events.append)
        self.assertEqual(self.api.cancel_run(self.run_payload(view))["data"]["status"], "cancelled")
        self.assertEqual(self.api.execute_run(self.run_payload(view))["error"]["code"], "invalid_state")
        self.assertEqual(self.executor.calls, [])
        self.assertEqual([event["event_type"] for event in events], ["run.cancelled"])

    def test_cancel_waiting_approval_persists_and_discards_decision(self):
        view = self.waiting()
        self.api.approve_tool(self.approval_payload(view))
        response = self.api.cancel_run(self.run_payload(view))
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["data"]["status"], "cancelled")
        self.assertIsNone(response["data"]["approval_decision"])
        self.assertEqual(self.store.load(view["run_id"]).to_dict()["run"]["status"], "cancelled")
        self.assertEqual(self.executor.calls, [])

    def test_observation_push_paging_and_failure_isolation(self):
        view = self.created()
        records = []
        def broken(record):
            raise ValueError("private listener details")
        self.api.subscribe_events(self.run_payload(view), broken)
        subscription = self.api.subscribe_events(self.run_payload(view), records.append)["data"]["subscription_id"]
        result = self.api.execute_run(self.run_payload(view))
        self.assertTrue(result["ok"], result)
        self.assertGreater(result["data"]["observer_failure_count"], 0)
        self.assertTrue(any(event["event_type"] == "run.observability.token_usage" for event in records))
        self.assertTrue(any(event["status"] == "completed" for event in records))
        self.assertEqual([r["cursor"] for r in records], list(range(1, len(records) + 1)))
        first = self.api.get_events(self.run_payload(view) | {"limit": 2})["data"]
        self.assertTrue(first["has_more"])
        second = self.api.get_events(self.run_payload(view) | {"after": first["next_cursor"], "limit": 200})["data"]
        self.assertEqual(len(first["events"]) + len(second["events"]), len(records))
        records[0]["payload"]["bad"] = "mutation"
        self.assertNotIn("bad", self.api.get_events(self.run_payload(view))["data"]["events"][0]["payload"])
        self.assertTrue(self.api.unsubscribe_events(self.run_payload(view) | {"subscription_id": subscription})["data"]["removed"])
        self.assertNotIn("private listener details", json.dumps(result))

    def test_event_cache_is_bounded_and_reports_gaps(self):
        api = RuntimeAPI(self.make_service(capacity=3), actor_id="local-user")
        view = self.created(api)
        api.execute_run(self.run_payload(view))
        page = api.get_events(self.run_payload(view))["data"]
        self.assertEqual(len(page["events"]), 3)
        self.assertTrue(page["truncated"])
        self.assertGreater(page["oldest_cursor"], 1)

    def test_provider_exception_is_sanitized_and_run_remains_queryable(self):
        class BrokenModel(Model):
            def generate(self, messages, **kwargs):
                raise RuntimeError("secret-key and provider stack")
        self.model_factory = BrokenModel
        view = self.created()
        result = self.api.execute_run(self.run_payload(view))
        self.assertEqual(result["error"]["code"], "execution_failed")
        self.assertNotIn("secret-key", json.dumps(result))
        queried = self.api.get_run(self.run_payload(view))["data"]
        self.assertEqual(queried["status"], "failed")
        self.assertFalse(queried["busy"])
        self.assertIsNotNone(queried["snapshot_revision"])

    def test_imported_approval_requires_fresh_host_decision(self):
        view = self.waiting()
        self.api.approve_tool(self.approval_payload(view))
        restored_service = self.make_service()
        restored_service.register_saved_run(view["run_id"], owner_id="local-user")
        restored = RuntimeAPI(restored_service, actor_id="local-user")
        result = restored.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})
        self.assertEqual(result["error"]["code"], "approval_required")
        self.assertTrue(restored.approve_tool(self.approval_payload(view))["ok"])
        self.assertTrue(restored.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})["ok"])
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(self.api.resume_run({"run_id": view["run_id"], "expected_revision": view["snapshot_revision"]})["error"]["code"], "snapshot_conflict")

    def test_cancel_imported_snapshot_persists_without_model_or_tool_execution(self):
        view = self.waiting()
        restored_service = self.make_service()
        restored_service.register_saved_run(view["run_id"], owner_id="local-user")
        restored = RuntimeAPI(restored_service, actor_id="local-user")
        result = restored.cancel_run(self.run_payload(view))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["status"], "cancelled")
        self.assertEqual(self.store.load(view["run_id"]).to_dict()["run"]["status"], "cancelled")
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.runners[-1].model.requests, [])

    def test_cancel_during_approval_resume_handoff_cannot_execute_tool(self):
        view = self.waiting()
        self.api.approve_tool(self.approval_payload(view))
        def cancel(event):
            if event["event_type"] == "run.tool.approval_resolved":
                self.api.cancel_run(self.run_payload(view))
        self.api.subscribe_events(self.run_payload(view), cancel)
        response = self.api.resume_run({
            "run_id": view["run_id"], "expected_revision": view["snapshot_revision"],
        })
        self.assertEqual(response["error"]["code"], "run_cancelled")
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.api.get_run(self.run_payload(view))["data"]["status"], "cancelled")

    def test_event_dto_covers_all_declared_concrete_events(self):
        from slothy.application.dto import EventDTO
        from slothy.core.events import EVENT_TYPES
        for event_class in EVENT_TYPES:
            event = event_class()
            record = EventDTO.from_event(event, 1, status="running", generation=0).to_dict()
            json.dumps(record, allow_nan=False)
            self.assertNotIn("arguments", record["payload"])
            self.assertNotIn("preview", record["payload"])

    def test_application_imports_only_its_own_layer_core_and_stdlib(self):
        root = Path(__file__).resolve().parents[2] / "src" / "slothy" / "application"
        forbidden = ("slothy.infrastructure", "slothy.presentation", "slothy.main", "openai", "webview", "sqlite3")
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                           [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                self.assertFalse(any(name.startswith(forbidden) for name in modules), str(path))

    def test_inflight_cancel_and_duplicate_execute(self):
        entered, release = threading.Event(), threading.Event()
        class BlockingModel(Model):
            def generate(self, messages, **kwargs):
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test worker not released")
                return super().generate(messages, **kwargs)
        self.model_factory = BlockingModel
        view = self.created()
        results = []
        worker = threading.Thread(target=lambda: results.append(self.api.execute_run(self.run_payload(view))))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.api.execute_run(self.run_payload(view))["error"]["code"], "run_busy")
            requested = self.api.cancel_run(self.run_payload(view))
            self.assertTrue(requested["data"]["cancel_requested"])
            self.assertTrue(self.api.get_run(self.run_payload(view))["data"]["busy"])
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]["error"]["code"], "run_cancelled")
        self.assertEqual(self.api.get_run(self.run_payload(view))["data"]["status"], "cancelled")
        self.assertEqual(self.executor.calls, [])

    def test_resume_updates_live_run_and_can_be_cancelled(self):
        view = self.created()
        def pause(event):
            if event["event_type"] == "run.tool.call_ended":
                self.api.interrupt_run(self.run_payload(view))
        subscription = self.api.subscribe_events(self.run_payload(view), pause)["data"]["subscription_id"]
        paused = self.api.execute_run(self.run_payload(view))
        self.assertTrue(paused["ok"], paused)
        self.assertEqual(paused["data"]["status"], "suspended")
        previous = self.runners[0].current_run
        self.api.unsubscribe_events(self.run_payload(view) | {"subscription_id": subscription})
        self.api.subscribe_events(self.run_payload(view), lambda event: self.api.cancel_run(self.run_payload(view))
                                  if event["event_type"] == "run.resumed" else None)
        response = self.api.resume_run({"run_id": view["run_id"], "expected_revision": paused["data"]["snapshot_revision"]})
        self.assertEqual(response["error"]["code"], "run_cancelled")
        self.assertIsNot(self.runners[0].current_run, previous)
        queried = self.api.get_run(self.run_payload(view))["data"]
        self.assertEqual(queried["status"], "cancelled")
        self.assertEqual(queried["generation"], 1)
        self.assertEqual(len(self.executor.calls), 1)


if __name__ == "__main__":
    unittest.main()
