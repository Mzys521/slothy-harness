"""Coding 设置用例；文件系统校验和 Runtime 组装由宿主注入。"""

from copy import deepcopy

from slothy.application.dto.requests import _fields
from slothy.application.errors import ApplicationError


class CodingService:
    def __init__(self, *, catalog, actor_id, defaults, validate, runtime_factory,
                 tool_catalog, check_presets):
        self.catalog, self.actor_id = catalog, actor_id
        self.defaults, self.validate = deepcopy(defaults), validate
        self.runtime_factory, self.tool_catalog = runtime_factory, tool_catalog
        self.check_presets = deepcopy(check_presets)

    def binding(self):
        return deepcopy(self.catalog.get(self.actor_id, "coding_settings", "default") or self.defaults)

    def settings(self):
        value = self.binding()
        value.pop("root_identity", None)
        return value

    def new_binding(self, project=None):
        binding = self.binding()
        if project is not None:
            if not project.get("workspace_root"):
                raise ApplicationError("coding_workspace_required", "请为项目添加源文件夹。")
            binding["workspace_root"] = project["workspace_root"]
            binding["root_identity"] = project["root_identity"]
        if not binding.get("workspace_root"):
            raise ApplicationError("coding_workspace_required", "请先在设置页配置 Coding Agent 工作目录。")
        try:
            settings = deepcopy(binding)
            settings.pop("root_identity", None)
            current = self.validate(settings)
            if current.get("root_identity") != binding.get("root_identity"):
                raise ValueError("workspace_changed")
        except ValueError:
            raise ApplicationError("coding_workspace_unavailable", "工作目录已移动、替换或不可用，请编辑项目重新添加源文件夹。") from None
        return binding

    def update(self, payload):
        _fields(payload, {"allow_edits", "allowed_checks", "check_timeout_seconds"}, {"workspace_root"})
        try:
            value = self.validate({**payload, "workspace_root": payload.get("workspace_root")})
            if "workspace_root" not in payload:
                original = self.binding()
                value["workspace_root"] = original.get("workspace_root")
                if "root_identity" in original:
                    value["root_identity"] = original["root_identity"]
        except ValueError:
            raise ApplicationError("invalid_coding_settings", "请填写存在的项目绝对路径，并检查权限、检查项目和超时设置。目录链接、系统根目录和受保护目录不可作为工作目录。") from None
        self.catalog.put(self.actor_id, "coding_settings", "default", value)
        return self.settings()

    def runtime(self, profile, binding=None):
        binding = self.binding() if binding is None else deepcopy(binding)
        if not binding.get("workspace_root"):
            raise ApplicationError("coding_workspace_required", "请先在设置页配置 Coding Agent 工作目录。")
        return self.runtime_factory(profile, binding)

    def tools(self):
        return {"ok": True, "data": self.tool_catalog(self.binding())}
