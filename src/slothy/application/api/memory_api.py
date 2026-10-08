"""记忆写入/查询的原子 JSON 接口，身份在可信宿主绑定。"""

from copy import deepcopy
from json import dumps, loads

from slothy.application.dto.requests import _fields
from slothy.application.errors import ApplicationError
from slothy.core.context import ContextError


class MemoryAPI:
    def __init__(self, service, *, actor_id):
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id 必须是可信宿主身份")
        self._service, self._actor_id = service, actor_id

    def remember(self, payload):
        def operation():
            value = _fields(payload, {"id", "text"}, {"entities", "source", "created_at"})
            return self._service.remember(value["id"], value["text"], actor_id=self._actor_id,
                                          **deepcopy({k: v for k, v in value.items() if k not in {"id", "text"}}))
        return self._invoke(operation)

    def search(self, payload):
        def operation():
            value = _fields(payload, {"query"}, {"entities"})
            return {"memories": self._service.search(value["query"], actor_id=self._actor_id,
                                                      entities=deepcopy(value.get("entities")))}
        return self._invoke(operation)

    @staticmethod
    def _invoke(operation):
        try:
            return loads(dumps({"ok": True, "data": operation()}, ensure_ascii=False, allow_nan=False))
        except ApplicationError as error:
            return {"ok": False, "error": error.dto.to_dict()}
        except ContextError:
            return {"ok": False, "error": {"code": "memory_error", "message": "记忆参数、配置或存储操作无效。", "run_id": None}}
        except Exception:
            return {"ok": False, "error": {"code": "internal_error", "message": "记忆操作失败。", "run_id": None}}
