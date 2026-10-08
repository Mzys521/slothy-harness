"""项目创建、编辑与目录选择；宿主文件操作由注入的适配器完成。"""

from copy import deepcopy
from uuid import uuid4

from slothy.application.dto.requests import _fields, _text
from slothy.application.errors import ApplicationError


def project_view(project):
    value = deepcopy(project)
    value.pop("root_identity", None)
    return value


class ProjectService:
    def __init__(self, catalog, actor_id, inspect_directory, picker=None):
        self.catalog, self.actor_id = catalog, actor_id
        self.inspect_directory, self.picker = inspect_directory, picker

    def _directory(self, value):
        try:
            return self.inspect_directory(_text(value, "workspace_root", maximum=1000))
        except ValueError:
            raise ApplicationError("invalid_project_directory", "请选择存在的项目文件夹。目录链接、系统根目录和受保护目录不可使用。") from None

    def inspect(self, payload):
        value = _fields(payload, {"workspace_root"})
        return project_view(self._directory(value["workspace_root"]))

    def choose_directory(self, payload):
        _fields(payload, set())
        if self.picker is None:
            return {"available": False, "directory": None}
        try:
            selected = self.picker()
        except Exception:
            raise ApplicationError("folder_picker_unavailable", "目录选择器暂不可用，请输入文件夹路径。") from None
        return {"available": True, "directory": project_view(self._directory(selected)) if selected else None}

    def create(self, payload):
        value = _fields(payload, {"name"}, {"workspace_root"})
        project = {"id": uuid4().hex, "name": _text(value["name"], "name", maximum=80).strip(), "pinned": False}
        # 旧的纯名称目录可继续读取/编辑；新 UI 必须附加已校验的源文件夹。
        if "workspace_root" in value:
            project.update(self._directory(value["workspace_root"]))
        self.catalog.put(self.actor_id, "project", project["id"], project)
        return project_view(project)

    def update(self, payload):
        value = _fields(payload, {"project_id"}, {"name", "workspace_root", "pinned"})
        project_id = _text(value["project_id"], "project_id")
        project = self.catalog.get(self.actor_id, "project", project_id)
        if project is None:
            raise ApplicationError("project_not_found", "项目不存在。")
        if len(value) < 2:
            raise ApplicationError("invalid_request", "没有需要更新的项目字段。")
        if "name" in value:
            project["name"] = _text(value["name"], "name", maximum=80).strip()
        if "pinned" in value:
            if type(value["pinned"]) is not bool:
                raise ApplicationError("invalid_request", "置顶状态必须为布尔值。")
            project["pinned"] = value["pinned"]
        if "workspace_root" in value:
            project.update(self._directory(value["workspace_root"]))
        self.catalog.put(self.actor_id, "project", project_id, project)
        return project_view(project)
