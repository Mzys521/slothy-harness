"""项目源文件夹 → Coding 绑定 → 编辑/恢复的真实离线集成测试。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from slothy.desktop import assemble_desktop
from test_coding_desktop import CodingModel, SOURCE


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "first"
        self.other = self.base / "second"
        for folder in (self.root, self.other):
            folder.mkdir()
            (folder / "sample.py").write_bytes(SOURCE)
        git = self.root / ".git"
        git.mkdir()
        (git / "config").write_text('[remote "origin"]\n url = git@github.com:Mzys521/slothy-harness.git\n', encoding="utf-8")
        self.bridge = assemble_desktop(data_dir=self.base / "data", model_factory=CodingModel, remote=False)

    def request(self, method, payload=None):
        result = self.bridge.request(method, {} if payload is None else payload)
        self.assertTrue(result["ok"], result)
        return result["data"]

    def project(self, root=None, name="代码项目"):
        return self.request("create_project", {"name": name, "workspace_root": str(root or self.root)})

    def task(self, project):
        return self.request("create_task", {"user_input": "读取 sample.py 并修复", "agent_mode": "coding",
                                           "project_id": project["id"], "profile": "advanced"})

    def test_project_metadata_is_validated_public_and_persisted(self):
        project = self.project(name="  第一项目  ")
        self.assertEqual(project["name"], "第一项目")
        self.assertEqual(project["repository"], {"label": "Mzys521/slothy-harness",
                         "url": "https://github.com/Mzys521/slothy-harness"})
        self.assertEqual(Path(project["workspace_root"]), self.root)
        self.assertNotIn("root_identity", project)
        updated = self.request("update_project", {"project_id": project["id"], "name": "重命名", "pinned": True})
        self.assertEqual(updated["id"], project["id"])
        self.assertTrue(updated["pinned"])
        restarted = assemble_desktop(data_dir=self.base / "data", remote=False)
        self.assertIn(updated, restarted.request("workspace", {})["data"]["projects"])

    def test_directory_and_project_inputs_cannot_inject_identity_or_ownership(self):
        for root in ("relative-directory", str(self.base / "missing"), str(self.root / "sample.py"), self.root.anchor):
            with self.subTest(root=root):
                result = self.bridge.request("create_project", {"name": "无效项目", "workspace_root": root})
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "invalid_project_directory")
        for payload in ({"name": "x", "root_identity": [1, 2]}, {"name": "x", "actor_id": "foreign"},
                        {"name": " "}, {"name": "x" * 81}):
            self.assertFalse(self.bridge.request("create_project", payload)["ok"])
        self.assertEqual(self.request("workspace")["projects"], [])
        project = self.project()
        self.assertFalse(self.bridge.request("update_project", {"project_id": project["id"], "pinned": 1})["ok"])
        self.assertFalse(self.bridge.request("update_project", {"project_id": project["id"]})["ok"])
        self.assertFalse(self.bridge.request("update_project", {"project_id": "missing", "name": "x"})["ok"])
        self.assertFalse(self.bridge.request("update_project", {"project_id": project["id"], "root_identity": [1, 2]})["ok"])
        catalog = self.bridge._api._service.catalog
        catalog.put("foreign", "project", "foreign-project", {"id": "foreign-project", "name": "隔离项目"})
        self.assertFalse(self.bridge.request("update_project", {"project_id": "foreign-project", "name": "侵入"})["ok"])

    def test_repository_display_omits_credentials_and_rejects_untrusted_urls(self):
        config = self.root / ".git" / "config"
        config.write_text('[remote "origin"]\n url = https://fixture-user:fixture-pass@github.com/org/repo.git?token=fixture\n', encoding="utf-8")
        value = self.request("inspect_project_directory", {"workspace_root": str(self.root)})
        self.assertEqual(value["repository"], {"label": "org/repo", "url": "https://github.com/org/repo"})
        self.assertNotIn("root_identity", value)
        for url in ("https://untrusted.invalid/org/repo", "javascript:alert(1)", "file:///local/repository"):
            config.write_text('[remote "origin"]\n url = ' + url + '\n', encoding="utf-8")
            self.assertIsNone(self.request("inspect_project_directory", {"workspace_root": str(self.root)})["repository"])
        config.write_bytes(b"\xff\xfeinvalid")
        self.assertIsNone(self.request("inspect_project_directory", {"workspace_root": str(self.root)})["repository"])

    def test_native_directory_selection_cancel_and_browser_fallback_are_explicit(self):
        self.assertEqual(self.request("choose_project_directory"), {"available": False, "directory": None})
        selected = iter((None, str(self.root), str(self.base / "missing")))
        native = assemble_desktop(data_dir=self.base / "native", remote=False, directory_picker=lambda: next(selected))
        self.assertEqual(native.request("choose_project_directory", {})["data"], {"available": True, "directory": None})
        response = native.request("choose_project_directory", {})
        self.assertEqual(Path(response["data"]["directory"]["workspace_root"]), self.root)
        self.assertNotIn("root_identity", response["data"]["directory"])
        self.assertEqual(native.request("choose_project_directory", {})["error"]["code"], "invalid_project_directory")
        self.assertEqual(native.request("choose_project_directory", {})["error"]["code"], "folder_picker_unavailable")
        self.assertFalse(native.request("choose_project_directory", {"workspace_root": str(self.root)})["ok"])

    def test_each_project_overrides_the_legacy_root_and_uses_current_permissions(self):
        self.request("update_coding_settings", {"workspace_root": str(self.other), "allow_edits": False,
                     "allowed_checks": [], "check_timeout_seconds": 8})
        first, second = self.project(), self.project(self.other, "第二项目")
        a, b = self.task(first), self.task(second)
        self.assertEqual(Path(a["coding_binding"]["workspace_root"]), self.root)
        self.assertEqual(Path(b["coding_binding"]["workspace_root"]), self.other)
        self.assertFalse(a["coding_binding"]["allow_edits"])
        self.assertEqual(a["coding_binding"]["allowed_checks"], [])
        # 权限更新不需要重新提交旧的全局目录，新任务通过自己的项目重新检查目录。
        changed = self.request("update_coding_settings", {"allow_edits": True,
                    "allowed_checks": ["python_unit"], "check_timeout_seconds": 12})
        self.assertEqual(Path(changed["workspace_root"]), self.other)
        c = self.task(first)
        self.assertTrue(c["coding_binding"]["allow_edits"])
        self.assertEqual(c["coding_binding"]["allowed_checks"], ["python_unit"])
        self.assertFalse(a["coding_binding"]["allow_edits"])

    def test_editing_project_does_not_retarget_a_pending_approved_task(self):
        project = self.project()
        task = self.task(project)
        run_id = task["run_id"]
        first = self.request("execute_run", {"run_id": run_id})
        self.assertEqual(first["status"], "waiting_approval")
        pending = self.request("get_approval", {"run_id": run_id})
        self.request("update_project", {"project_id": project["id"], "workspace_root": str(self.other)})
        replacement = self.task(project)
        self.assertEqual(Path(replacement["coding_binding"]["workspace_root"]), self.other)
        self.request("approve_tool", {"run_id": run_id, "request_id": pending["request_id"],
                     "expected_revision": pending["snapshot_revision"]})
        run = self.request("get_run", {"run_id": run_id})
        self.request("resume_run", {"run_id": run_id, "expected_revision": run["snapshot_revision"]})
        self.assertEqual((self.root / "sample.py").read_bytes(), b"VALUE = 2\n")
        self.assertEqual((self.other / "sample.py").read_bytes(), SOURCE)
        restarted = assemble_desktop(data_dir=self.base / "data", remote=False)
        saved = restarted.request("workspace", {})["data"]["tasks"]
        original = next(item for item in saved if item["run_id"] == run_id)
        self.assertEqual(Path(original["coding_binding"]["workspace_root"]), self.root)

    def test_replaced_project_root_is_rejected_before_creating_a_run(self):
        project = self.project()
        self.root.rename(self.base / "moved-first")
        self.root.mkdir()
        result = self.bridge.request("create_task", {"user_input": "读取", "agent_mode": "coding", "project_id": project["id"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "coding_workspace_unavailable")
        self.assertEqual(self.request("workspace")["tasks"], [])
        self.request("update_project", {"project_id": project["id"], "workspace_root": str(self.root)})
        self.assertEqual(Path(self.task(project)["coding_binding"]["workspace_root"]), self.root)

    def test_name_only_legacy_project_can_be_upgraded_and_chat_needs_no_directory(self):
        project = self.request("create_project", {"name": "原有项目"})
        result = self.bridge.request("create_task", {"user_input": "读取", "agent_mode": "coding", "project_id": project["id"]})
        self.assertEqual(result["error"]["code"], "coding_workspace_required")
        self.request("update_project", {"project_id": project["id"], "workspace_root": str(self.root)})
        self.assertEqual(Path(self.task(project)["coding_binding"]["workspace_root"]), self.root)
        chat = self.request("create_task", {"user_input": "聊天", "agent_mode": "general", "project_id": None})
        self.assertEqual(chat["agent_mode"], "general")
        self.assertNotIn("coding_binding", chat)
        self.assertEqual(self.request("workspace")["status"]["agent_modes"],
                         {"general": {"label": "slothy chat"}, "coding": {"label": "sloty coding"}})


if __name__ == "__main__":
    unittest.main()
