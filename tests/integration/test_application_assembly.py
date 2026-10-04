"""实际计算执行器与 Application/Context/Policy/快照组装；模型使用替身。"""

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from slothy.application.api import RuntimeAPI
from slothy.application.services import RuntimeService
from slothy.core.context import InMemoryContext
from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.runtime import AgentRunner
from slothy.core.tools import ToolRegistry
from slothy.infrastructure.app_tools import CalculatorToolExecutor, tool_list
from slothy.infrastructure.persistence.runtime_store import SQLiteSnapshotStore
from slothy.main import assemble_demo, demo_summarizer, main


class LastToolModel(ModelProvider):
    def generate(self, messages, **kwargs):
        if messages[-1]["role"] == "tool":
            return ModelResult(text="完成")
        return ModelResult(tool_calls=[ToolCall("calc-1", "add", {"a": 1.0, "b": 2.0})])


class ApplicationAssemblyTests(unittest.TestCase):
    def test_main_default_demo_composes_all_capabilities_without_network(self):
        stream = StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main([]), 0)
        output = stream.getvalue()
        for marker in ("[context]", "[policy] retry", "[usage]", "[observation]", "[run.resumed]", "status=completed", "budget=8192"):
            self.assertIn(marker, output)

    def test_summary_and_trim_are_injected_with_same_application_service(self):
        for summarizer, strategy in ((None, "trim_oldest"), (demo_summarizer, "summarize")):
            assembly = assemble_demo(summarizer=summarizer)
            created = assembly.api.create_run({"user_input": "验证"})["data"]
            result = assembly.api.execute_run({"run_id": created["run_id"]})
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["data"]["status"], "completed")
            events = assembly.api.get_events({"run_id": created["run_id"], "limit": 200})["data"]["events"]
            self.assertTrue(any(event["payload"].get("strategy") == strategy for event in events))
            self.assertGreater(assembly.contexts[0].estimator.estimate(assembly.contexts[0].get_history()), 8192)
            self.assertLessEqual(max(assembly.models[0].request_tokens), 8192)

    def test_step_policy_is_enforced_through_the_same_api(self):
        assembly = assemble_demo(max_steps=5)
        view = assembly.api.create_run({"user_input": "验证"})["data"]
        result = assembly.api.execute_run({"run_id": view["run_id"]})
        self.assertEqual(result["error"]["code"], "step_limit_reached")
        self.assertEqual(assembly.api.get_run({"run_id": view["run_id"]})["data"]["step_count"], 5)

    def test_saved_run_can_resume_via_a_new_service_and_sqlite_store(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.sqlite"
            registry = ToolRegistry()
            registry.register_many(tool_list)
            def service(store):
                return RuntimeService(
                    lambda: AgentRunner(
                        LastToolModel(), registry, CalculatorToolExecutor(registry),
                        context=InMemoryContext(), snapshot_store=store,
                    ), registry, snapshot_store=store,
                )
            first_store = SQLiteSnapshotStore(path)
            first_service = service(first_store)
            api = RuntimeAPI(first_service, actor_id="owner")
            created = api.create_run({"user_input": "1 + 2"})["data"]
            received = []
            def pause(event):
                received.append(event)
                if event["event_type"] == "run.tool.call_ended":
                    api.interrupt_run({"run_id": created["run_id"]})
            api.subscribe_events({"run_id": created["run_id"]}, pause)
            paused = api.execute_run({"run_id": created["run_id"]})
            self.assertTrue(paused["ok"], paused)
            self.assertEqual(paused["data"]["status"], "suspended")
            new_store = SQLiteSnapshotStore(path)
            new_service = service(new_store)
            new_service.register_saved_run(created["run_id"], owner_id="owner")
            restored = RuntimeAPI(new_service, actor_id="owner")
            result = restored.resume_run({
                "run_id": created["run_id"], "expected_revision": paused["data"]["snapshot_revision"],
            })
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["data"]["status"], "completed")
            self.assertEqual(result["data"]["generation"], 1)
            events = restored.get_events({"run_id": created["run_id"]})["data"]["events"]
            self.assertFalse(any(event["event_type"] == "run.tool.call_started" for event in events))
            self.assertEqual(new_store.load(created["run_id"]).to_dict()["run"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
