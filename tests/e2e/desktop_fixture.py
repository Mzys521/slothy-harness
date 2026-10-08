"""离线 E2E 宿主：真实 HTTP/Application/SQLite，外部模型显式替身。"""

from pathlib import Path
from dataclasses import replace
import sys
from tempfile import TemporaryDirectory
from time import sleep
from xml.etree.ElementTree import fromstring
from json import loads
from hashlib import sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from test_desktop import DesktopTestModel
from slothy.desktop import assemble_desktop
from slothy.presentation.desktop.server import create_server
from slothy.core.model import ModelResult, ModelUsage, ToolCall
from slothy.core.tools import ReplaySafety


class UITestModel(DesktopTestModel):
    """仅测试宿主支持可观察的长调用；生产宿主没有此替身。"""

    def generate(self, messages, **kwargs):
        root = fromstring("<context>" + "\n".join(m["content"] for m in messages) + "</context>")
        current = root.findtext("current_user_input")[1:-1]
        if current.startswith("E2E Coding"):
            self.calls += 1
            if self.calls == 1:
                return ModelResult(tool_calls=[ToolCall("read", "read_file", {"path": "sample.py"})])
            if self.calls == 2:
                return ModelResult(tool_calls=[ToolCall("edit", "edit_file", {"path": "sample.py", "old_text": "VALUE = 1", "new_text": "VALUE = 2", "expected_sha256": sha256(b"VALUE = 1\n").hexdigest()})])
            if self.calls == 3:
                return ModelResult(tool_calls=[ToolCall("check", "run_checks", {"preset": "python_unit"})])
            return ModelResult(text="Coding 工具流程已完成，详见检查结果。")
        if current.startswith("E2E 记忆："):
            return ModelResult(text="前一轮任务已完成", usage=ModelUsage(total_tokens=1))
        if current == "我刚刚问了什么？":
            memories = loads(root.findtext("long_term_memory"))
            previous = memories[0]["text"].split("历史用户输入：\n", 1)[1] if memories else "没有已完成历史"
            return ModelResult(text="你上一轮问的是：" + previous, usage=ModelUsage(total_tokens=1))
        if current.startswith("E2E 控制"):
            self.calls += 1
            if self.calls == 1:
                sleep(3)
            return ModelResult(text="控制用例完成", usage=ModelUsage(total_tokens=1))
        return super().generate(messages, **kwargs)


class ApprovalRegistry:
    """quick 测试模式为 add 注入真实的不可验证重放声明以触发审批。"""

    def __init__(self, registry):
        self.registry = registry

    def definitions(self):
        return self.registry.definitions()

    def get_tool(self, name):
        definition = self.registry.get_tool(name)
        return replace(definition, replay_safety=ReplaySafety.UNVERIFIABLE) if name == "add" else definition


def main():
    with TemporaryDirectory(prefix="slothy-ui-test-") as directory:
        coding_root = Path(directory) / "coding-project"
        tests = coding_root / "tests" / "unit"
        tests.mkdir(parents=True)
        (coding_root / "sample.py").write_bytes(b"VALUE = 1\n")
        (tests / "test_value.py").write_text("import unittest\nfrom pathlib import Path\nclass Check(unittest.TestCase):\n def test_value(self): self.assertEqual((Path(__file__).parents[2] / 'sample.py').read_text().strip(), 'VALUE = 2')\n", encoding="utf-8")
        git = coding_root / ".git"
        git.mkdir()
        (git / "config").write_text('[remote "origin"]\n url = git@github.com:Mzys521/slothy-harness.git\n', encoding="utf-8")
        second_root = Path(directory) / "second-project"
        second_root.mkdir()
        (second_root / "sample.py").write_bytes(b"VALUE = 1\n")
        bridge = assemble_desktop(data_dir=directory, model_factory=UITestModel, remote=False)
        original_create = bridge._api._service.create_task
        def delayed_create(payload):
            if "创建期间切换" in payload.get("user_input", ""):
                sleep(0.7)  # 仅测试宿主模拟较慢的目录/快照创建。
            return original_create(payload)
        bridge._api._service.create_task = delayed_create
        quick = bridge._api._service.runtimes["quick"]._service
        base_factory = quick._runner_factory

        def approval_factory():
            runner = base_factory()
            runner.registry = ApprovalRegistry(runner.registry)
            return runner

        quick._runner_factory = approval_factory
        # 测试服务明确声明自己的注入模型；生产启动没有此替换入口。
        bridge._api._service.status["model"] = {"configured": True, "provider": "test", "name": "test-chat"}
        bridge._api._service.status["test_coding_root"] = str(coding_root)
        bridge._api._service.status["test_second_root"] = str(second_root)
        server = create_server(bridge, frontend="frontend/dist", port=8766)
        print("Slothy E2E fixture: http://127.0.0.1:8766 (test-chat, no external API)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
