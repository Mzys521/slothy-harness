"""桌面传输 + 真实 Application/Core/SQLite；只有外部生成模型为测试替身。"""

from http.client import HTTPConnection
from json import dumps, loads
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from slothy.core.events import TransientModelError
from slothy.desktop import assemble_desktop
from slothy.presentation.desktop.server import create_server


class DesktopTestModel(ModelProvider):
    def __init__(self):
        super().__init__(model="test-chat")
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise TransientModelError("test retry")
        if self.calls == 2:
            return ModelResult(tool_calls=[ToolCall("lookup", "search_memory", {"query": "A-123"})], usage=ModelUsage(total_tokens=3, prompt_tokens=2, completion_tokens=1))
        if self.calls == 3:
            return ModelResult(tool_calls=[ToolCall("calc", "add", {"a": 18.5, "b": 23.8})], usage=ModelUsage(total_tokens=3, prompt_tokens=2, completion_tokens=1))
        if kwargs.get("on_chunk"):
            kwargs["on_chunk"]("计算完成：42.3")
        return ModelResult(text="计算完成：42.3", usage=ModelUsage(total_tokens=3, prompt_tokens=2, completion_tokens=1))


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.bridge = assemble_desktop(data_dir=self.path, model_factory=DesktopTestModel, remote=False)

    def create(self, profile="advanced"):
        result = self.bridge.request("create_task", {"user_input": "检索订单并计算", "profile": profile})
        self.assertTrue(result["ok"], result)
        return result["data"]

    def test_workspace_is_real_empty_history_with_separate_inspiration_templates(self):
        result = self.bridge.request("workspace", {})["data"]
        self.assertEqual(result["tasks"], [])
        self.assertEqual(len(result["inspirations"]), 3)
        self.assertFalse(result["status"]["capabilities"]["schedules"])
        self.assertFalse(result["status"]["model"]["configured"])

    def test_project_and_inspiration_persist_across_service_restart(self):
        project = self.bridge.request("create_project", {"name": "界面工程"})["data"]
        inspiration = self.bridge.request("save_inspiration", {"title": "自己的想法", "prompt": "先计划再行动"})["data"]
        restarted = assemble_desktop(data_dir=self.path, model_factory=DesktopTestModel, remote=False)
        result = restarted.request("workspace", {})["data"]
        self.assertIn(project, result["projects"])
        self.assertIn(inspiration, result["inspirations"])

    def test_create_is_atomic_and_profiles_inject_real_policy_limits(self):
        quick, advanced = self.create("quick"), self.create("advanced")
        self.assertEqual(quick["run"]["status"], "idle")
        self.assertEqual(quick["run"]["step_count"], 0)
        self.assertEqual(quick["run"]["max_steps"], 5)
        self.assertEqual(advanced["run"]["max_steps"], 20)
        self.assertFalse(self.bridge.request("create_task", {"user_input": "x", "profile": "other"})["ok"])
        self.assertFalse(self.bridge.request("create_task", {"user_input": "x", "actor_id": "foreign"})["ok"])

    def test_real_tool_events_and_context_inspection_are_safe_and_budgeted(self):
        self.assertTrue(self.bridge.request("remember", {"id": "order", "text": "订单 A-123", "source": "test"})["ok"])
        task = self.create()
        result = self.bridge.request("execute_run", {"run_id": task["run_id"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["status"], "completed")
        inspection = self.bridge.request("inspect_run", {"run_id": task["run_id"]})["data"]
        self.assertEqual(inspection["task_state"]["goal"], task["goal"])
        self.assertEqual(inspection["model"], "test-chat")
        self.assertEqual(inspection["usage"]["total_tokens"], 9)
        self.assertLessEqual(inspection["context_report"]["input_tokens"], inspection["context_report"]["input_budget"])
        self.assertNotIn("active", inspection)
        self.assertNotIn("api_key", dumps(inspection))
        events = self.bridge.request("get_events", {"run_id": task["run_id"], "limit": 200})["data"]["events"]
        names = [e["payload"]["name"] for e in events if e["event_type"] == "run.tool.call_started"]
        self.assertEqual(names, ["search_memory", "add"])
        self.assertTrue(any(e["event_type"] == "run.policy.triggered" and e["payload"]["decision"] == "retry" for e in events))

    def test_completed_run_restores_without_model_or_tool_reexecution(self):
        task = self.create()
        self.bridge.request("execute_run", {"run_id": task["run_id"]})
        def forbidden():
            model = DesktopTestModel()
            model.generate = lambda *args, **kwargs: self.fail("恢复查询不应调用模型")
            return model
        restarted = assemble_desktop(data_dir=self.path, model_factory=forbidden, remote=False)
        view = restarted.request("inspect_run", {"run_id": task["run_id"]})
        self.assertTrue(view["ok"], view)
        self.assertEqual(view["data"]["run"]["output"], "计算完成：42.3")

    def test_unknown_operations_and_foreign_runs_are_rejected(self):
        self.assertFalse(self.bridge.request("__getattribute__", {})["ok"])
        self.assertFalse(self.bridge.request("inspect_run", {"run_id": "foreign"})["ok"])
        self.assertFalse(self.bridge.request("create_project", {"name": "x", "path": "C:/"})["ok"])
        self.assertFalse(self.bridge.request("get_events", {"run_id": self.create()["run_id"], "actor_id": "foreign"})["ok"])

    def test_local_http_enforces_origin_header_json_size_and_static_boundary(self):
        root = self.path / "frontend"
        root.mkdir()
        (root / "index.html").write_text("<h1>Slothy</h1>", encoding="utf-8")
        (root / "local.sqlite3").write_text("private runtime data", encoding="utf-8")
        server = create_server(self.bridge, frontend=root, port=0)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            def post(method, body="{}", headers=None):
                connection = HTTPConnection("127.0.0.1", server.server_port)
                connection.request("POST", "/api/" + method, body, {"Content-Type": "application/json", "X-Slothy-Client": "desktop-ui", **(headers or {})})
                response = connection.getresponse()
                result = (response.status, loads(response.read()))
                connection.close()
                return result
            self.assertTrue(post("workspace")[1]["ok"])
            self.assertEqual(post("workspace", headers={"Origin": "http://malicious.invalid"})[0], 403)
            self.assertEqual(post("workspace", headers={"X-Slothy-Client": ""})[0], 403)
            self.assertEqual(post("workspace", "not json")[0], 400)
            self.assertFalse(post("__getattribute__")[1]["ok"])
            connection = HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/%2e%2e/runtime.sqlite3")
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            connection.close()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/local.sqlite3")
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == "__main__":
    unittest.main()
