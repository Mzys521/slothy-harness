"""真实临时文件系统及本地子进程；不访问网络或模型 API。"""

from hashlib import sha256
import os
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from slothy.core.model import ToolCall
from slothy.core.tools import ReplaySafety, ToolContext, ToolRegistry
from slothy.infrastructure.app_tools import CalculatorToolExecutor, add_tool
from slothy.infrastructure.coding import CodingToolExecutor, coding_tools, validate_settings
from slothy.infrastructure.coding.checks import OUTPUT_BYTES, child_environment, run_command
from slothy.infrastructure.coding.workspace import CodingError, MAX_FILE_BYTES


class CodingToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = validate_settings({"workspace_root": str(self.root)})
        self.registry = ToolRegistry()
        self.registry.register_many((add_tool, *coding_tools(self.settings)))
        self.executor = CodingToolExecutor(self.registry, CalculatorToolExecutor(self.registry), self.settings)
        self.original = b"# example\r\nVALUE = 1\r\n"
        (self.root / "sample.py").write_bytes(self.original)
        self.digest = sha256(self.original).hexdigest()

    def call(self, name, arguments, *, approved=False):
        return self.executor.execute(ToolCall("test", name, arguments),
            ToolContext("run", approval_id="host-grant" if approved else ""))

    def test_read_pagination_and_literal_search_skip_private_and_generated_files(self):
        (self.root / ".env").write_text("SECRET=never read", encoding="utf-8")
        (self.root / ".env.example").write_text("VALUE=placeholder", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "junk.js").write_text("VALUE junk", encoding="utf-8")
        page = self.call("read_file", {"path": "sample.py", "max_lines": 1}).output
        self.assertEqual(page["sha256"], self.digest)
        self.assertEqual(page["content"], "# example\r\n")
        self.assertEqual(page["next_line"], 2)
        self.assertEqual(self.call("read_file", {"path": "sample.py", "start_line": 2}).output["content"], "VALUE = 1\r\n")
        matches = self.call("search_code", {"query": "VALUE"}).output["matches"]
        self.assertEqual({match["path"] for match in matches}, {"sample.py", ".env.example"})
        self.assertEqual(self.call("search_code", {"query": ".*"}).output["matches"], [])
        listing = self.call("list_files", {"recursive": True}).output
        self.assertEqual({entry["path"] for entry in listing["entries"]}, {"sample.py", ".env.example"})

    def test_paths_secrets_oversize_binary_and_unknown_arguments_are_rejected(self):
        for path in ("../escape", "C:/Windows/test", "\\\\server\\share\\test", "sample.py:stream", ".env", ".git/config", ".aws/config", "server.pem"):
            with self.subTest(path=path):
                self.assertTrue(self.call("read_file", {"path": path}).is_error)
        (self.root / "binary").write_bytes(b"\x00\xff")
        (self.root / "huge").write_bytes(b"a" * (MAX_FILE_BYTES + 1))
        self.assertEqual(self.call("read_file", {"path": "binary"}).output["code"], "not_utf8_text")
        self.assertEqual(self.call("read_file", {"path": "huge"}).output["code"], "file_too_large")
        self.assertEqual(self.call("read_file", {"path": "sample.py", "shell": "anything"}).output["code"], "invalid_tool_arguments")

    def test_edit_requires_single_approval_digest_and_unique_match_then_preserves_bytes(self):
        args = {"path": "sample.py", "old_text": "VALUE = 1", "new_text": "VALUE = 2", "expected_sha256": self.digest}
        self.assertEqual(self.call("edit_file", args).output["code"], "approval_required")
        self.assertEqual((self.root / "sample.py").read_bytes(), self.original)
        self.assertEqual(self.call("edit_file", {**args, "expected_sha256": "0" * 64}, approved=True).output["code"], "file_changed")
        result = self.call("edit_file", args, approved=True)
        self.assertFalse(result.is_error, result)
        self.assertEqual((self.root / "sample.py").read_bytes(), self.original.replace(b"1", b"2"))
        self.assertEqual(self.call("edit_file", args, approved=True).output["code"], "file_changed")
        duplicated = "repeat repeat"
        (self.root / "repeated.txt").write_text(duplicated, encoding="utf-8")
        result = self.call("edit_file", {"path": "repeated.txt", "old_text": "repeat", "new_text": "new",
                           "expected_sha256": sha256(duplicated.encode()).hexdigest()}, approved=True)
        self.assertEqual(result.output["code"], "edit_match_not_unique")

    def test_write_is_approved_and_never_blindly_overwrites_existing_files(self):
        args = {"path": "src/new.py", "content": "print('hello')\n"}
        self.assertTrue(self.call("write_file", args).is_error)
        self.assertFalse((self.root / "src").exists())
        self.assertFalse(self.call("write_file", args, approved=True).is_error)
        self.assertEqual(self.call("write_file", {**args, "content": "overwritten"}, approved=True).output["code"], "file_changed")
        (self.root / "bom.txt").write_bytes(b"\xef\xbb\xbfhello\r\n")
        digest = sha256((self.root / "bom.txt").read_bytes()).hexdigest()
        self.assertFalse(self.call("edit_file", {"path": "bom.txt", "old_text": "hello", "new_text": "你好", "expected_sha256": digest}, approved=True).is_error)
        self.assertEqual((self.root / "bom.txt").read_bytes(), b"\xef\xbb\xbf" + "你好\r\n".encode())

    def test_hardlinks_and_replaced_workspace_identity_are_rejected(self):
        os.link(self.root / "sample.py", self.root / "linked.py")
        self.assertEqual(self.call("read_file", {"path": "linked.py"}).output["code"], "linked_path")
        self.executor.workspace.identity = (-1, -1)
        self.assertEqual(self.call("list_files", {}).output["code"], "workspace_changed")

    def test_symbolic_links_cannot_cross_workspace(self):
        with TemporaryDirectory() as outside:
            target = Path(outside) / "private.txt"
            target.write_text("outside", encoding="utf-8")
            try:
                (self.root / "link.txt").symlink_to(target)
            except OSError:
                if os.name != "nt":
                    raise
                # Windows 无 symlink 权限时，用同样具有 reparse 标记的真实 junction 验证边界。
                junction = self.root / "junction"
                created = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", str(junction), outside],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                self.assertEqual(created.returncode, 0, "临时 junction 创建失败")
                self.assertEqual(self.call("read_file", {"path": "junction/private.txt"}).output["code"], "linked_path")
                self.assertNotIn("junction/private.txt", str(self.call("list_files", {"recursive": True}).output))
                return
            self.assertEqual(self.call("read_file", {"path": "link.txt"}).output["code"], "linked_path")

    def test_settings_enforce_root_and_limits_and_control_registered_capabilities(self):
        for settings in ({"workspace_root": "relative"}, {"workspace_root": str(Path(self.root.anchor))},
                         {"check_timeout_seconds": True}, {"check_timeout_seconds": 121},
                         {"allowed_checks": ["shell"]}, {"actor_id": "other"}):
            with self.subTest(settings=settings), self.assertRaises(CodingError):
                validate_settings(settings)
        readonly = {**self.settings, "allow_edits": False, "allowed_checks": []}
        self.assertEqual({tool.name for tool in coding_tools(readonly)}, {"list_files", "read_file", "search_code"})
        limited = coding_tools({**self.settings, "allowed_checks": ["python_unit"]})
        schema = next(tool.parameters for tool in limited if tool.name == "run_checks")
        self.assertEqual(schema["properties"]["preset"]["enum"], ["python_unit"])
        for tool in coding_tools(self.settings):
            self.assertEqual(tool.replay_safety, ReplaySafety.UNVERIFIABLE if tool.name in {"edit_file", "write_file", "run_checks"} else ReplaySafety.IDEMPOTENT)

    def test_checks_use_fixed_args_require_approval_and_return_actual_exit_status(self):
        folder = self.root / "tests" / "unit"
        folder.mkdir(parents=True)
        (folder / "test_example.py").write_text("import unittest\nclass Check(unittest.TestCase):\n def test_example(self): self.assertEqual(1, 1)\n", encoding="utf-8")
        self.assertEqual(self.call("run_checks", {"preset": "python_unit"}).output["code"], "approval_required")
        result = self.call("run_checks", {"preset": "python_unit"}, approved=True)
        self.assertFalse(result.is_error, result)
        self.assertEqual(result.output["exit_code"], 0)
        self.assertIn("Ran 1 test", result.output["output"])
        (folder / "test_example.py").write_text("import unittest\nclass Check(unittest.TestCase):\n def test_example(self): self.fail('actual failure')\n", encoding="utf-8")
        self.assertTrue(self.call("run_checks", {"preset": "python_unit"}, approved=True).is_error)
        self.assertEqual(self.call("run_checks", {"preset": "python_unit", "command": "anything"}, approved=True).output["code"], "invalid_tool_arguments")
        self.executor.settings["allowed_checks"] = []
        self.assertEqual(self.call("run_checks", {"preset": "python_unit"}, approved=True).output["code"], "check_not_allowed")

    def test_child_environment_omits_provider_keys_and_output_and_wait_are_bounded(self):
        with patch.dict(os.environ, {"API_KEY": "test-private", "DASHSCOPE_API_KEY": "test-private", "PYTHONPATH": "untrusted"}):
            env = child_environment()
            self.assertNotIn("API_KEY", env)
            self.assertNotIn("DASHSCOPE_API_KEY", env)
            self.assertNotIn("PYTHONPATH", env)
        large = run_command([sys.executable, "-c", "print('x' * 200000)"], self.root, 5)
        self.assertTrue(large["truncated"])
        self.assertLessEqual(len(large["output"].encode()), OUTPUT_BYTES)
        timeout = run_command([sys.executable, "-c", "import time; time.sleep(20)"], self.root, 0.2)
        self.assertTrue(timeout["timed_out"])
        self.assertLess(timeout["duration_ms"], 6000)


if __name__ == "__main__":
    unittest.main()
