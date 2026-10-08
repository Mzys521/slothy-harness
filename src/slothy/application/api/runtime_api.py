"""稳定的 Python 接口，适合由 Presentation 桥接；所有响应均为 JSON 数据。"""

from collections.abc import Callable
from json import dumps, loads

from slothy.application.dto.requests import (
    ApprovalCommandRequest, CreateRunRequest, EventsRequest, ListRunsRequest,
    ResumeRunRequest, RunRequest, UnsubscribeRequest, _fields,
)
from slothy.application.errors import ApplicationError
from slothy.application.services import RuntimeService


def _wire(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_wire(item) for item in value]
    return value


class RuntimeAPI:
    def __init__(self, service: RuntimeService, *, actor_id: str):
        """actor_id 由可信宿主绑定，不能从模型参数或前端请求中读取。"""
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id must be a nonempty host identity")
        self._service, self._actor_id = service, actor_id

    def create_run(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.create_run(
            CreateRunRequest.parse(payload).user_input, actor_id=self._actor_id,
        ))

    def execute_run(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.execute_run(
            RunRequest.parse(payload).run_id, actor_id=self._actor_id,
        ))

    def start_run(self, payload: dict) -> dict:
        """execute_run 的同义入口；必须先创建 Run。"""
        return self.execute_run(payload)

    def get_run(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.get_run(
            RunRequest.parse(payload).run_id, actor_id=self._actor_id,
        ))

    def inspect_run(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.inspect_run(
            RunRequest.parse(payload).run_id, actor_id=self._actor_id,
        ))

    def list_runs(self, payload: dict | None = None) -> dict:
        def operation():
            request = ListRunsRequest.parse({} if payload is None else payload)
            return self._service.list_runs(
                actor_id=self._actor_id, offset=request.offset, limit=request.limit,
            )
        return self._invoke(operation)

    def cancel_run(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.cancel_run(
            RunRequest.parse(payload).run_id, actor_id=self._actor_id,
        ))

    def interrupt_run(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.interrupt_run(
            RunRequest.parse(payload).run_id, actor_id=self._actor_id,
        ))

    def resume_run(self, payload: dict) -> dict:
        def operation():
            request = ResumeRunRequest.parse(payload)
            return self._service.resume_run(
                request.run_id, request.expected_revision, actor_id=self._actor_id,
            )
        return self._invoke(operation)

    def get_approval(self, payload: dict) -> dict:
        return self._invoke(lambda: self._service.get_approval(
            RunRequest.parse(payload).run_id, actor_id=self._actor_id,
        ))

    def approve_tool(self, payload: dict) -> dict:
        return self._decide(payload, approved=True)

    def reject_tool(self, payload: dict) -> dict:
        return self._decide(payload, approved=False)

    def _decide(self, payload: dict, *, approved: bool) -> dict:
        def operation():
            request = ApprovalCommandRequest.parse(payload)
            return self._service.decide_tool(
                request.run_id, request.request_id, request.expected_revision,
                approved=approved, actor_id=self._actor_id,
            )
        return self._invoke(operation)

    def list_tools(self, payload: dict | None = None) -> dict:
        def operation():
            _fields({} if payload is None else payload, set())
            return self._service.list_tools()
        return self._invoke(operation)

    def get_events(self, payload: dict) -> dict:
        def operation():
            request = EventsRequest.parse(payload)
            return self._service.get_events(
                request.run_id, actor_id=self._actor_id, after=request.after, limit=request.limit,
            )
        return self._invoke(operation)

    def subscribe_events(self, payload: dict, listener: Callable[[dict], None]) -> dict:
        """Presentation 在 Python 侧绑定回调；前端不能上传可执行回调。"""
        def operation():
            subscription_id = self._service.subscribe_events(
                RunRequest.parse(payload).run_id, listener, actor_id=self._actor_id,
            )
            return {"subscription_id": subscription_id}
        return self._invoke(operation)

    def unsubscribe_events(self, payload: dict) -> dict:
        def operation():
            request = UnsubscribeRequest.parse(payload)
            return {"removed": self._service.unsubscribe_events(
                request.run_id, request.subscription_id, actor_id=self._actor_id,
            )}
        return self._invoke(operation)

    @staticmethod
    def _invoke(operation: Callable) -> dict:
        try:
            data = _wire(operation())
            return loads(dumps({"ok": True, "data": data}, ensure_ascii=False, allow_nan=False))
        except ApplicationError as error:
            return {"ok": False, "error": error.dto.to_dict()}
        except Exception:
            return {"ok": False, "error": {
                "code": "internal_error", "message": "应用操作失败。", "run_id": None,
            }}
