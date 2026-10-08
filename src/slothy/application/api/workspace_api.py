"""桌面 JSON API；静态方法白名单，没有反射式任意调用。"""

from json import dumps, loads

from slothy.application.errors import ApplicationError


RUNTIME_OPERATIONS = frozenset({"execute_run", "get_run", "inspect_run", "get_events",
    "cancel_run", "interrupt_run", "resume_run", "get_approval", "approve_tool", "reject_tool"})
OPERATIONS = RUNTIME_OPERATIONS | {"workspace", "create_task", "create_project",
    "save_inspiration", "list_tools", "search_memory", "remember", "update_coding_settings",
    "update_project", "inspect_project_directory", "choose_project_directory",
    "model_settings", "save_model_provider", "select_model", "remove_model_key",
    "test_model_connection", "refresh_provider_models"}


class WorkspaceAPI:
    def __init__(self, service):
        self._service = service

    def request(self, method, payload):
        try:
            if not isinstance(method, str) or method not in OPERATIONS or not isinstance(payload, dict):
                raise ApplicationError("invalid_request", "未知操作或请求格式无效。")
            if method in RUNTIME_OPERATIONS:
                response = self._service.runtime_operation(method, payload)
            elif method in {"remember", "search_memory"}:
                response = getattr(self._service.memory, "remember" if method == "remember" else "search")(payload)
            elif method in {"create_task", "list_tools"}:
                response = getattr(self._service, method)(payload)
            else:
                response = {"ok": True, "data": getattr(self._service, method)(payload)}
            return loads(dumps(response, ensure_ascii=False, allow_nan=False))
        except ApplicationError as error:
            return {"ok": False, "error": error.dto.to_dict()}
        except Exception:
            return {"ok": False, "error": {"code": "application_error", "message": "操作失败，请检查配置或稍后重试。", "run_id": None}}
