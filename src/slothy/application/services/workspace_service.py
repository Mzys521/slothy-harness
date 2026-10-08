"""桌面用例：归属目录与既有 Runtime / Memory API 的原子路由。"""

from copy import deepcopy
from uuid import uuid4

from slothy.application.dto.requests import _fields, _text
from slothy.application.errors import ApplicationError
from slothy.core.runtime.catalog import WorkspaceCatalog
from .project_service import project_view


class WorkspaceService:
    def __init__(self, *, catalog: WorkspaceCatalog, runtimes: dict, memory, actor_id,
                 status: dict, coding=None, projects=None, models=None):
        self.catalog, self.runtimes, self.memory = catalog, runtimes, memory
        self.actor_id, self.status = actor_id, deepcopy(status)
        self.coding = coding
        self.projects = projects
        self.models = models

    def _runtime(self, task):
        if task.get("model_binding") and self.models is not None:
            return self.models.runtime(task["profile"], task["model_binding"], task.get("coding_binding"))
        if task.get("agent_mode", "general") == "coding":
            if self.coding is None:
                raise ApplicationError("coding_unavailable", "Coding Agent 尚未启用。")
            return self.coding.runtime(task["profile"], task["coding_binding"])
        return self.runtimes[task["profile"]]

    def workspace(self, payload):
        _fields(payload, set())
        tasks = self.catalog.list(self.actor_id, "task")
        # 状态取自运行服务；重启目录只指认宿主已加载的快照，不自动执行。
        for task in tasks:
            try:
                response = self._runtime(task).get_run({"run_id": task["run_id"]})
            except (ApplicationError, ValueError, KeyError):
                response = {"ok": False}
            task["run"] = response.get("data")
            task["available"] = response["ok"]
        status = deepcopy(self.status)
        if self.models is not None:
            status["model_settings"] = self.models.configuration()
            status["model"] = self.models.status(status["model"])
        if self.coding is not None:
            status["coding_settings"] = self.coding.settings()
            status["check_presets"] = self.coding.check_presets
        return {"status": status, "tasks": tasks,
                "projects": [project_view(project) for project in self.catalog.list(self.actor_id, "project")],
                "inspirations": self.catalog.list(self.actor_id, "inspiration")}

    def create_project(self, payload):
        if self.projects is not None:
            return self.projects.create(payload)
        value = _fields(payload, {"name"})
        name = _text(value["name"], "name", maximum=80)
        project = {"id": uuid4().hex, "name": name}
        self.catalog.put(self.actor_id, "project", project["id"], project)
        return project

    def update_project(self, payload):
        return self.projects.update(payload)

    def inspect_project_directory(self, payload):
        return self.projects.inspect(payload)

    def choose_project_directory(self, payload):
        return self.projects.choose_directory(payload)

    def save_inspiration(self, payload):
        value = _fields(payload, {"title", "prompt"})
        item = {"id": uuid4().hex, "title": _text(value["title"], "title", maximum=100),
                "prompt": _text(value["prompt"], "prompt", maximum=8000)}
        self.catalog.put(self.actor_id, "inspiration", item["id"], item)
        return item

    def create_task(self, payload):
        value = _fields(payload, {"user_input"}, {"project_id", "profile", "agent_mode", "model_binding"})
        profile = value.get("profile", "quick")
        if not isinstance(profile, str) or profile not in self.runtimes:
            raise ApplicationError("invalid_request", "请选择快速或进阶模式。")
        project_id = value.get("project_id")
        project = self.catalog.get(self.actor_id, "project", project_id) if isinstance(project_id, str) else None
        if project_id is not None and project is None:
            raise ApplicationError("invalid_request", "项目不存在。")
        text = _text(value["user_input"], "user_input", maximum=100000)
        mode = value.get("agent_mode", "general")
        if mode not in ("general", "coding"):
            raise ApplicationError("invalid_request", "请选择通用助手或 Coding Agent。")
        binding = None
        if mode == "coding":
            if self.coding is None:
                raise ApplicationError("coding_unavailable", "Coding Agent 尚未启用。")
            binding = self.coding.new_binding(project)
            runtime = self.coding.runtime(profile, binding)
        else:
            runtime = self.runtimes[profile]
        model_binding = None
        if self.models is not None:
            model_binding = self.models.new_binding(value.get("model_binding"))
            if model_binding is not None:
                runtime = self.models.runtime(profile, model_binding, binding)
        response = runtime.create_run({"user_input": text})
        if not response["ok"]:
            return response
        run = response["data"]
        task = {"run_id": run["run_id"], "title": text[:60], "goal": text,
                "profile": profile, "project_id": project_id, "agent_mode": mode}
        if binding is not None:
            task["coding_binding"] = binding
        if model_binding is not None:
            task["model_binding"] = model_binding
        try:
            self.catalog.put(self.actor_id, "task", run["run_id"], task)
        except Exception:
            runtime.cancel_run({"run_id": run["run_id"]})
            raise ApplicationError("storage_error", "任务目录保存失败，未调用模型。") from None
        return {"ok": True, "data": {**task, "run": run}}

    def runtime_operation(self, method, payload):
        # 不允许前端指定用户归属；未知 Run 与越权均不可见。
        if not isinstance(payload, dict) or not isinstance(payload.get("run_id"), str):
            raise ApplicationError("invalid_request", "缺少执行标识。")
        task = self.catalog.get(self.actor_id, "task", payload["run_id"])
        if task is None:
            raise ApplicationError("run_not_found", "执行不存在。")
        return getattr(self._runtime(task), method)(payload)

    def list_tools(self, payload):
        value = _fields(payload, set(), {"agent_mode"})
        mode = value.get("agent_mode", "general")
        if mode == "coding" and self.coding is not None:
            return self.coding.tools()
        if mode != "general":
            raise ApplicationError("invalid_request", "工具模式无效。")
        return self.runtimes["quick"].list_tools({})

    def update_coding_settings(self, payload):
        if self.coding is None:
            raise ApplicationError("coding_unavailable", "Coding Agent 尚未启用。")
        return self.coding.update(payload)


    def model_settings(self, payload):
        return self.models.configuration(payload)

    def save_model_provider(self, payload):
        return self.models.save(payload)

    def select_model(self, payload):
        return self.models.select(payload)

    def remove_model_key(self, payload):
        return self.models.remove(payload)

    def test_model_connection(self, payload):
        return self.models.test(payload)

    def refresh_provider_models(self, payload):
        return self.models.refresh(payload)
