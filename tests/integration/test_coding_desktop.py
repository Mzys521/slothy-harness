"""Coding 模式 → 受控工具 → 持久化审批 → 文件效果的完整离线闭环。"""

from hashlib import sha256
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.desktop import assemble_desktop


SOURCE = b"VALUE = 1\n"
DIGEST = sha256(SOURCE).hexdigest()


class CodingModel(ModelProvider):
    def __init__(self, stage=0):
        super().__init__(model="offline-coding")
        self.stage = stage
        self.schemas = []

    def generate(self, messages, **kwargs):
        self.schemas.append(dumps(kwargs.get("tools"), ensure_ascii=False))
        self.stage += 1
        if self.stage == 1:
            return ModelResult(tool_calls=[ToolCall("read", "read_file", {"path": "sample.py"})])
        if self.stage == 2:
            return ModelResult(tool_calls=[ToolCall("edit", "edit_file", {"path": "sample.py", "old_text": "VALUE = 1", "new_text": "VALUE = 2", "expected_sha256": DIGEST})])
        if self.stage == 3:
            return ModelResult(tool_calls=[ToolCall("check", "run_checks", {"preset": "python_unit"})])
        return ModelResult(text="代码任务完成，检查结果以工具返回为准。")


class CodingDesktopTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.other = self.base / "other"
        self.other.mkdir()
        (self.root / "sample.py").write_bytes(SOURCE)
        (self.other / "sample.py").write_bytes(SOURCE)
        folder = self.root / "tests" / "unit"
        folder.mkdir(parents=True)
        (folder / "test_value.py").write_text("import unittest\nfrom pathlib import Path\nclass Check(unittest.TestCase):\n def test_value(self): self.assertEqual((Path(__file__).parents[2] / 'sample.py').read_text().strip(), 'VALUE = 2')\n", encoding="utf-8")
        self.model = CodingModel()
        self.bridge = assemble_desktop(data_dir=self.base / "data", model_factory=lambda: self.model, remote=False)

    def request(self, method, payload):
        result = self.bridge.request(method, payload)
        self.assertTrue(result["ok"], result)
        return result["data"]

    def settings(self, root=None, **changes):
        return self.request("update_coding_settings", {"workspace_root": str(root or self.root),
            "allow_edits": True, "allowed_checks": ["python_unit"], "check_timeout_seconds": 10, **changes})

    def create(self):
        return self.request("create_task", {"user_input": "修复 VALUE 并测试", "agent_mode": "coding", "profile": "advanced"})

    def decide_resume(self, run_id, approved=True):
        pending = self.request("get_approval", {"run_id": run_id})
        self.request("approve_tool" if approved else "reject_tool", {"run_id": run_id,
            "request_id": pending["request_id"], "expected_revision": pending["snapshot_revision"]})
        run = self.request("get_run", {"run_id": run_id})
        return self.request("resume_run", {"run_id": run_id, "expected_revision": run["snapshot_revision"]})

    def test_configuration_required_persisted_and_mode_catalogs_are_isolated(self):
        self.assertIsNone(self.request("workspace", {})["status"]["coding_settings"]["workspace_root"])
        denied = self.bridge.request("create_task", {"user_input": "read", "agent_mode": "coding"})
        self.assertEqual(denied["error"]["code"], "coding_workspace_required")
        general = self.request("list_tools", {})
        self.assertEqual({tool["name"] for tool in general}, {"add", "search_memory", "get_result"})
        settings = self.settings()
        self.assertEqual(Path(settings["workspace_root"]), self.root.resolve())
        coding = self.request("list_tools", {"agent_mode": "coding"})
        self.assertIn("edit_file", {tool["name"] for tool in coding})
        self.assertEqual(set(coding[0]), set(general[0]))
        restarted = assemble_desktop(data_dir=self.base / "data", remote=False)
        self.assertEqual(restarted.request("workspace", {})["data"]["status"]["coding_settings"], settings)
        self.settings(allow_edits=False, allowed_checks=[])
        self.assertEqual({tool["name"] for tool in self.request("list_tools", {"agent_mode": "coding"})},
                         {"add", "search_memory", "get_result", "list_files", "read_file", "search_code"})

    def test_real_edit_and_check_each_wait_for_approval_and_memory_waits_for_completion(self):
        self.settings()
        task = self.create()
        run_id = task["run_id"]
        self.assertEqual(task["run"]["max_steps"], 60)
        first = self.request("execute_run", {"run_id": run_id})
        self.assertEqual(first["status"], "waiting_approval")
        self.assertEqual((self.root / "sample.py").read_bytes(), SOURCE)
        self.assertEqual(self.request("get_approval", {"run_id": run_id})["tool_name"], "edit_file")
        self.assertEqual(self.request("search_memory", {"query": "修复 VALUE"})["memories"], [])
        second = self.decide_resume(run_id)
        self.assertEqual(second["status"], "waiting_approval")
        self.assertEqual((self.root / "sample.py").read_bytes(), b"VALUE = 2\n")
        self.assertEqual(self.request("get_approval", {"run_id": run_id})["tool_name"], "run_checks")
        final = self.decide_resume(run_id)
        self.assertEqual(final["status"], "completed")
        memories = self.request("search_memory", {"query": "修复 VALUE"})["memories"]
        self.assertTrue(memories)
        self.assertTrue(any("read_file" in schema for schema in self.model.schemas))
        details = self.request("inspect_run", {"run_id": run_id})
        self.assertLessEqual(details["context_report"]["input_tokens"], details["context_report"]["input_budget"])
        events = self.request("get_events", {"run_id": run_id, "limit": 200})["events"]
        checks = [event for event in events if event["event_type"] == "run.tool.call_ended" and event["payload"].get("name") == "run_checks"]
        self.assertTrue(checks)
        self.assertFalse(checks[-1]["payload"]["is_error"])
        self.assertNotIn("VALUE = 2", dumps(events))

    def test_settings_change_and_restart_keep_pending_task_bound_to_original_workspace(self):
        self.settings()
        task = self.create()
        run_id = task["run_id"]
        self.request("execute_run", {"run_id": run_id})
        self.settings(self.other, allow_edits=False, allowed_checks=[])
        self.bridge = assemble_desktop(data_dir=self.base / "data", model_factory=lambda: CodingModel(stage=3), remote=False)
        pending = self.request("get_approval", {"run_id": run_id})
        self.assertEqual(pending["tool_name"], "edit_file")
        final = self.decide_resume(run_id)
        self.assertEqual(final["status"], "completed")
        self.assertEqual((self.root / "sample.py").read_bytes(), b"VALUE = 2\n")
        self.assertEqual((self.other / "sample.py").read_bytes(), SOURCE)
        persisted = self.request("workspace", {})["tasks"][0]
        self.assertEqual(Path(persisted["coding_binding"]["workspace_root"]), self.root.resolve())

    def test_rejection_and_stale_file_after_approval_never_mutate_the_file(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                self.model = CodingModel()
                self.settings()
                task = self.create()
                self.request("execute_run", {"run_id": task["run_id"]})
                if approved:
                    (self.root / "sample.py").write_bytes(b"VALUE = 7\n")
                run = self.decide_resume(task["run_id"], approved)
                self.assertEqual(run["status"], "waiting_approval")  # 下一项检查仍需另一次批准。
                expected = b"VALUE = 7\n" if approved else SOURCE
                self.assertEqual((self.root / "sample.py").read_bytes(), expected)

    def test_invalid_tool_path_is_rejected_before_approval(self):
        class InvalidModel(CodingModel):
            def generate(inner, messages, **kwargs):
                inner.stage += 1
                if inner.stage == 1:
                    return ModelResult(tool_calls=[ToolCall("escape", "write_file", {"path": "../escape.txt", "content": "no"})])
                return ModelResult(text="路径不可用")
        self.model = InvalidModel()
        self.settings()
        task = self.create()
        final = self.request("execute_run", {"run_id": task["run_id"]})
        self.assertEqual(final["status"], "completed")
        self.assertFalse((self.base / "escape.txt").exists())
        self.assertFalse(self.bridge.request("get_approval", {"run_id": task["run_id"]})["ok"])

    def test_new_tasks_recheck_the_configured_workspace_before_model_creation(self):
        self.settings()
        self.root.rename(self.base / "moved-project")
        result = self.bridge.request("create_task", {"user_input": "读取项目", "agent_mode": "coding"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "coding_workspace_unavailable")
        self.assertEqual(self.model.stage, 0)
        self.assertEqual(self.request("workspace", {})["tasks"], [])


if __name__ == "__main__":
    unittest.main()
