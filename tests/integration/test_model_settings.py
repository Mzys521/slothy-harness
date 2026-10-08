"""真实 SDK + MockTransport + Application/Core/SQLite，完全不访问外部 API。"""

from json import dumps, loads
from xml.etree.ElementTree import fromstring
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import httpx2 as httpx
except ImportError:
    import httpx
from openai import OpenAI

from slothy.desktop import assemble_desktop
from slothy.infrastructure.llm.providers.catalog import PROVIDERS


class ModelAPITransport:
    """本地 HTTP 替身只替换外部供应商，SDK 解析、流式、工具往返保持真实。"""
    def __init__(self):
        self.requests = []
        self.failure = None

    def factory(self, **kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(self.handle), follow_redirects=False))

    def handle(self, request):
        body = loads(request.content) if request.content else {}
        self.requests.append({"host": request.url.host, "path": request.url.path,
                              "authorization": request.headers.get("authorization"), "body": body})
        failure = self.failure or (401 if "fake-invalid" in request.headers.get("authorization", "") else None)
        if failure:
            return httpx.Response(failure, json={"error": {"message": "private raw upstream error " + request.headers.get("authorization", ""), "type": "authentication_error"}})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": "account-text-model", "object": "model", "created": 0, "owned_by": "test"},
                {"id": "text-embedding-v3", "object": "model", "created": 0, "owned_by": "test"},
            ]})
        messages = body["messages"]
        context = fromstring("<context>" + "\n".join(item.get("content") or "" for item in messages if item["role"] == "user") + "</context>")
        working = loads(context.findtext("working_memory") or "{}")
        tool = bool(body.get("tools")) and "验证工具" in (context.findtext("current_user_input") or "") and not any(item["role"] == "tool" for item in working.get("messages", []))
        model = body["model"]
        text = "已完成：" + model
        usage = {"total_tokens": 7, "prompt_tokens": 4, "completion_tokens": 3}
        if not body.get("stream"):
            return httpx.Response(200, json={"id": "test-completion", "object": "chat.completion", "created": 0, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}], "usage": usage})
        def chunk(delta, reason=None):
            return {"id": "test-completion", "object": "chat.completion.chunk", "created": 0, "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}
        if tool:
            chunks = [chunk({"tool_calls": [{"index": 0, "id": "call-add", "type": "function", "function": {"name": "a", "arguments": '{"a":1'}}]}),
                      chunk({"tool_calls": [{"index": 0, "function": {"name": "dd", "arguments": '1,"b":2}'}}]}, "tool_calls")]
        else:
            chunks = [chunk({"role": "assistant", "content": "已完成："}), chunk({"content": model}, "stop")]
        chunks.append({"id": "test-completion", "object": "chat.completion.chunk", "created": 0, "model": model, "choices": [], "usage": usage})
        payload = "".join("data: " + dumps(item, ensure_ascii=False) + "\n\n" for item in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=payload.encode(), headers={"Content-Type": "text/event-stream"})


class ModelSettingsIntegrationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.transport = ModelAPITransport()
        self.bridge = self.assemble()

    def assemble(self):
        return assemble_desktop(data_dir=self.path / "desktop", remote=False, model_client_factory=self.transport.factory)

    def api(self, method, payload=None):
        result = self.bridge.request(method, payload or {})
        self.assertTrue(result["ok"], result)
        return result["data"]

    def save(self, provider_id="deepseek", **options):
        return self.api("save_model_provider", {"provider_id": provider_id, "api_key": "fake-key-" + provider_id, **options})

    def create(self, **options):
        return self.api("create_task", {"user_input": "验证工具", "profile": "advanced", **options})

    def test_api_key_only_configures_all_four_providers_and_real_streaming_tools(self):
        for provider_id, definition in PROVIDERS.items():
            with self.subTest(provider=provider_id):
                settings = self.save(provider_id)
                task = self.create()
                self.assertEqual(task["model_binding"]["model"], definition["default_model"])
                run = self.api("execute_run", {"run_id": task["run_id"]})
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["output"], "已完成：" + definition["default_model"])
                request = self.transport.requests[-1]
                self.assertEqual(request["authorization"], "Bearer fake-key-" + provider_id)
                self.assertEqual(request["body"]["messages"][-1]["role"], "user")
                self.assertIn("working_memory", request["body"]["messages"][-1]["content"])
                self.assertIn("13", request["body"]["messages"][-1]["content"])
                self.assertTrue(request["body"]["stream"])
                expected = {"enable_thinking": False} if provider_id == "qwen" else {"thinking": {"type": "disabled"}}
                for key, value in expected.items():
                    self.assertEqual(request["body"][key], value)
                self.assertNotIn("fake-key-", dumps(settings))
                self.assertNotIn('"api_key":', dumps(settings))
                details = self.api("inspect_run", {"run_id": task["run_id"]})
                self.assertEqual(details["model"], definition["default_model"])
                self.assertEqual(details["usage"]["total_tokens"], 14)

    def test_selection_and_custom_models_do_not_rebind_existing_tasks(self):
        self.save()
        old = self.create()
        self.save("qwen", model="qwen3-coder-plus")
        new = self.create()
        self.api("execute_run", {"run_id": old["run_id"]})
        self.assertEqual(self.transport.requests[-1]["body"]["model"], "deepseek-flash")
        self.api("execute_run", {"run_id": new["run_id"]})
        self.assertEqual(self.transport.requests[-1]["body"]["model"], "qwen3-coder-plus")
        self.assertNotIn("enable_thinking", self.transport.requests[-1]["body"])
        self.api("save_model_provider", {"provider_id": "qwen", "model": "qwen-custom-snapshot"})
        self.api("select_model", {"provider_id": "qwen", "model": "qwen-plus"})
        settings = self.api("model_settings")
        self.assertIn("qwen-custom-snapshot", next(item for item in settings["providers"] if item["id"] == "qwen")["models"])
        self.assertEqual(settings["selection"]["model"], "qwen-plus")
        before = len(self.transport.requests)
        self.bridge = self.assemble()
        self.assertEqual(self.api("workspace")["status"]["model"]["name"], "qwen-plus")
        self.assertEqual(self.api("inspect_run", {"run_id": old["run_id"]})["model"], "deepseek-flash")
        self.assertEqual(len(self.transport.requests), before, "恢复查询不能调用供应商")

    def test_coding_task_keeps_model_binding_across_restart(self):
        project_root = self.path / "project"
        project_root.mkdir()
        (project_root / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
        project = self.api("create_project", {"name": "Coding", "workspace_root": str(project_root)})
        self.save("glm")
        task = self.create(agent_mode="coding", project_id=project["id"])
        self.save("mimo")
        result = self.api("execute_run", {"run_id": task["run_id"]})
        self.assertEqual(result["status"], "completed")
        before = len(self.transport.requests)
        self.bridge = self.assemble()
        self.assertEqual(self.api("inspect_run", {"run_id": task["run_id"]})["model"], "glm-5")
        self.assertEqual(len(self.transport.requests), before)
        self.assertEqual(self.transport.requests[-1]["body"]["model"], "glm-5")
        names = [item["function"]["name"] for item in self.transport.requests[-1]["body"]["tools"]]
        self.assertIn("read_file", names)
        self.assertIn("edit_file", names)

    def test_region_credentials_are_independent_and_must_be_explicitly_configured(self):
        self.save("qwen")
        result = self.bridge.request("save_model_provider", {"provider_id": "qwen", "endpoint_id": "international"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "model_not_configured")
        self.save("qwen", endpoint_id="international", api_key="fake-key-international")
        task = self.create()
        self.api("execute_run", {"run_id": task["run_id"]})
        self.assertEqual(self.transport.requests[-1]["host"], "dashscope-intl.aliyuncs.com")
        self.assertEqual(self.transport.requests[-1]["authorization"], "Bearer fake-key-international")
        self.api("remove_model_key", {"provider_id": "qwen", "endpoint_id": "international"})
        config = self.api("model_settings")
        endpoints = next(item for item in config["providers"] if item["id"] == "qwen")["endpoints"]
        self.assertTrue(next(item for item in endpoints if item["id"] == "china")["configured"])
        self.assertFalse(next(item for item in endpoints if item["id"] == "international")["configured"])

    def test_connection_probe_model_refresh_and_authentication_errors_are_safe(self):
        self.save()
        probe = self.api("test_model_connection", {"provider_id": "deepseek"})
        self.assertTrue(probe["connected"])
        request = self.transport.requests[-1]["body"]
        self.assertEqual(request["max_tokens"], 8)
        self.assertNotIn("tools", request)
        config = self.api("refresh_provider_models", {"provider_id": "deepseek"})
        provider = next(item for item in config["providers"] if item["id"] == "deepseek")
        self.assertIn("account-text-model", provider["models"])
        self.assertNotIn("text-embedding-v3", provider["models"])
        self.api("select_model", {"provider_id": "deepseek", "model": "account-text-model"})
        self.transport.failure = 401
        result = self.bridge.request("test_model_connection", {"provider_id": "deepseek"})
        self.assertEqual(result["error"]["code"], "model_authentication_error")
        self.assertNotIn("fake-key", dumps(result))
        task = self.create()
        failed = self.bridge.request("execute_run", {"run_id": task["run_id"]})
        self.assertEqual(failed["error"]["code"], "model_authentication_error")
        self.assertNotIn("private raw upstream", dumps(failed))
        self.assertNotIn("fake-key", dumps(self.api("get_events", {"run_id": task["run_id"]})))

    def test_key_rotation_and_removal_affect_only_matching_provider_credentials(self):
        self.save()
        task = self.create()
        self.save("glm")
        self.api("save_model_provider", {"provider_id": "deepseek", "api_key": "fake-rotated-key"})
        self.api("execute_run", {"run_id": task["run_id"]})
        self.assertEqual(self.transport.requests[-1]["authorization"], "Bearer fake-rotated-key")
        pending = self.create()
        self.api("remove_model_key", {"provider_id": "deepseek"})
        self.assertEqual(self.api("workspace")["status"]["model"]["provider"], "glm")
        failure = self.bridge.request("execute_run", {"run_id": pending["run_id"]})
        self.assertEqual(failure["error"]["code"], "model_not_configured")

    def test_keys_never_enter_catalog_snapshots_history_or_public_responses(self):
        self.save()
        task = self.create()
        self.api("execute_run", {"run_id": task["run_id"]})
        for method, payload in (("workspace", {}), ("model_settings", {}),
                                ("inspect_run", {"run_id": task["run_id"]}),
                                ("get_events", {"run_id": task["run_id"]}),
                                ("search_memory", {"query": "验证工具"})):
            self.assertNotIn("fake-key-deepseek", dumps(self.api(method, payload)))
        for path in (self.path / "desktop").rglob("*"):
            if path.is_file():
                self.assertNotIn(b"fake-key-deepseek", path.read_bytes(), path.name)

    def test_untrusted_payloads_and_unregistered_models_are_rejected(self):
        for payload in ({"provider_id": "unknown", "api_key": "fake"},
                        {"provider_id": "deepseek", "api_key": "fake", "base_url": "https://attacker.invalid"},
                        {"provider_id": "deepseek", "api_key": "fake bad key"},
                        {"provider_id": "deepseek", "api_key": "fake", "model": "embedding-v3"},
                        {"provider_id": "deepseek", "api_key": "fake", "actor_id": "foreign"}):
            self.assertFalse(self.bridge.request("save_model_provider", payload)["ok"])
        self.save()
        self.assertFalse(self.bridge.request("select_model", {"provider_id": "deepseek", "model": "unregistered"})["ok"])
        self.assertFalse(self.bridge.request("create_task", {"user_input": "x", "model_binding": {"provider_id": "deepseek", "endpoint_id": "standard", "model": "unregistered"}})["ok"])
        self.assertFalse(self.bridge.request("model_settings", {"actor_id": "foreign"})["ok"])
        self.save("mimo")
        self.assertEqual(self.bridge.request("refresh_provider_models", {"provider_id": "mimo"})["error"]["code"], "model_catalog_unsupported")


if __name__ == "__main__":
    unittest.main()
