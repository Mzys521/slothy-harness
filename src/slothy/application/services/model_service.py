"""提供商设置与模型选择用例；凭据和 SDK 能力由宿主注入。"""

from copy import deepcopy
from threading import RLock

from slothy.application.dto.requests import _fields
from slothy.application.errors import ApplicationError


class ModelService:
    def __init__(self, *, catalog, actor_id, providers, credentials, validate,
                 runtime_factory, provider_factory):
        self.catalog, self.actor_id = catalog, actor_id
        self.providers = deepcopy(providers)
        self.credentials, self.validate = credentials, validate
        self.runtime_factory, self.provider_factory = runtime_factory, provider_factory
        self._lock = RLock()

    def _provider(self, provider_id):
        if not isinstance(provider_id, str):
            raise ApplicationError("invalid_provider", "请选择模型提供商。")
        found = next((item for item in self.providers if item["id"] == provider_id), None)
        if found is None:
            raise ApplicationError("invalid_provider", "模型提供商无效。")
        return found

    def _settings(self, provider_id):
        return self.catalog.get(self.actor_id, "model_provider", provider_id) or {}

    def _binding(self, payload):
        provider = self._provider(payload.get("provider_id"))
        saved = self._settings(provider["id"])
        binding = {"provider_id": provider["id"],
                   "endpoint_id": payload.get("endpoint_id", saved.get("endpoint_id", provider["endpoints"][0]["id"])),
                   "model": payload.get("model", saved.get("model", provider["default_model"]))}
        try:
            return self.validate(binding)
        except ValueError:
            raise ApplicationError("invalid_model_settings", "请选择有效的服务区域并填写文本模型 ID。") from None

    def _has(self, binding):
        return self.credentials.has(self.actor_id, binding["provider_id"], binding["endpoint_id"])

    def binding(self):
        with self._lock:
            selection = self.catalog.get(self.actor_id, "model_selection", "default")
            if selection and selection.get("binding"):
                try:
                    return self.validate(selection["binding"])
                except ValueError:
                    raise ApplicationError("invalid_model_settings", "已保存的模型设置无效，请重新选择模型。") from None
            return None

    def configuration(self, payload=None):
        if payload is not None:
            _fields(payload, set())
        with self._lock:
            result = []
            for provider in self.providers:
                item = deepcopy(provider)
                saved = self._settings(item["id"])
                item["endpoint_id"] = saved.get("endpoint_id", item["endpoints"][0]["id"])
                item["model"] = saved.get("model", item["default_model"])
                item["models"] = list(dict.fromkeys([*item["models"], *saved.get("models", []), item["model"]]))
                for endpoint in item["endpoints"]:
                    endpoint["configured"] = self.credentials.has(self.actor_id, item["id"], endpoint["id"])
                item["configured"] = next((endpoint["configured"] for endpoint in item["endpoints"] if endpoint["id"] == item["endpoint_id"]), False)
                result.append(item)
            return {"providers": result, "selection": self.binding(), "storage_kind": self.credentials.storage_kind}

    def status(self, fallback):
        binding = self.binding()
        if binding is None:
            return deepcopy(fallback)
        return {"configured": self._has(binding), "provider": binding["provider_id"], "name": binding["model"]}

    def save(self, payload):
        _fields(payload, {"provider_id"}, {"endpoint_id", "model", "api_key"})
        with self._lock:
            binding = self._binding(payload)
            key = payload.get("api_key")
            if key is not None and (not isinstance(key, str) or not 1 <= len(key.strip()) <= 4096
                                    or any(ord(character) < 33 or ord(character) > 126 for character in key.strip())):
                raise ApplicationError("invalid_api_key", "请输入有效的 API Key，密钥不能包含空格或控制字符。")
            if key is None and not self._has(binding):
                raise ApplicationError("model_not_configured", "请填写当前提供商及服务区域的 API Key。")
            saved = self._settings(binding["provider_id"])
            models = list(dict.fromkeys([*saved.get("models", []), binding["model"]]))[-128:]
            if key is not None:
                try:
                    self.credentials.put(self.actor_id, binding["provider_id"], binding["endpoint_id"], key.strip())
                except Exception:
                    raise ApplicationError("credential_storage_error", "API Key 加密保存失败，请检查本机凭据存储。") from None
            self.catalog.put(self.actor_id, "model_provider", binding["provider_id"], {"model": binding["model"], "endpoint_id": binding["endpoint_id"], "models": models})
            self.catalog.put(self.actor_id, "model_selection", "default", {"binding": binding})
            return self.configuration()

    def select(self, payload):
        _fields(payload, {"provider_id", "model"}, {"endpoint_id"})
        with self._lock:
            binding = self._binding(payload)
            if not self._has(binding):
                raise ApplicationError("model_not_configured", "请先在设置中配置该提供商及服务区域的 API Key。")
            provider = self._provider(binding["provider_id"])
            saved = self._settings(binding["provider_id"])
            if binding["model"] not in {*provider["models"], *saved.get("models", []), saved.get("model")}:
                raise ApplicationError("invalid_model_settings", "请先在设置中添加该模型 ID。")
            self.catalog.put(self.actor_id, "model_provider", binding["provider_id"],
                             {**saved, "model": binding["model"], "endpoint_id": binding["endpoint_id"]})
            self.catalog.put(self.actor_id, "model_selection", "default", {"binding": binding})
            return self.configuration()

    def remove(self, payload):
        _fields(payload, {"provider_id"}, {"endpoint_id"})
        with self._lock:
            binding = self._binding(payload)
            try:
                self.credentials.delete(self.actor_id, binding["provider_id"], binding["endpoint_id"])
            except Exception:
                raise ApplicationError("credential_storage_error", "API Key 移除失败，请检查本机凭据存储。") from None
            selected = self.binding()
            if selected and (selected["provider_id"], selected["endpoint_id"]) == (binding["provider_id"], binding["endpoint_id"]):
                replacement = None
                for provider in self.providers:
                    for endpoint in provider["endpoints"]:
                        candidate = self._binding({"provider_id": provider["id"], "endpoint_id": endpoint["id"]})
                        if self._has(candidate):
                            replacement = candidate
                            break
                    if replacement is not None:
                        break
                if replacement is not None:
                    saved = self._settings(replacement["provider_id"])
                    self.catalog.put(self.actor_id, "model_provider", replacement["provider_id"],
                                     {**saved, "endpoint_id": replacement["endpoint_id"], "model": replacement["model"]})
                self.catalog.put(self.actor_id, "model_selection", "default", {"binding": replacement})
            return self.configuration()

    def _network(self, payload, *, listing=False):
        _fields(payload, {"provider_id"}, {"endpoint_id", "model"})
        binding = self._binding(payload)
        if not self._has(binding):
            raise ApplicationError("model_not_configured", "请先保存当前提供商及服务区域的 API Key。")
        if listing and not self._provider(binding["provider_id"])["can_list_models"]:
            raise ApplicationError("model_catalog_unsupported", "当前接入未启用模型列表刷新，可直接添加模型 ID。")
        try:
            provider = self.provider_factory(binding)
            if not listing:
                provider.test_connection()
                return {"connected": True, **binding}
            models = provider.list_models()
        except Exception as error:
            code = getattr(error, "error_code", "model_connection_error")
            messages = {
                "model_authentication_error": "API Key 无效或没有访问权限，请检查提供商和服务区域。",
                "model_not_found": "模型不存在或当前账号不可用，请检查模型 ID。",
                "llm_timeout": "连接测试超时，请稍后重试。",
                "model_transient_error": "模型服务限流或暂时不可用，请稍后重试。",
                "model_catalog_empty": "提供商没有返回文本模型，可直接添加模型 ID。",
            }
            raise ApplicationError(code if code in messages else "model_connection_error",
                                   messages.get(code, "请求失败，请检查模型配置或稍后重试。")) from None
        with self._lock:
            saved = self._settings(binding["provider_id"])
            saved["models"] = list(dict.fromkeys([*saved.get("models", []), *models]))[-256:]
            self.catalog.put(self.actor_id, "model_provider", binding["provider_id"], saved)
            return self.configuration()

    def test(self, payload):
        return self._network(payload)

    def refresh(self, payload):
        return self._network(payload, listing=True)

    def new_binding(self, requested=None):
        with self._lock:
            if requested is None:
                binding = self.binding()
            else:
                if not isinstance(requested, dict) or set(requested) != {"provider_id", "endpoint_id", "model"}:
                    raise ApplicationError("invalid_model_settings", "任务模型设置无效。")
                binding = self._binding(requested)
                provider = self._provider(binding["provider_id"])
                saved = self._settings(binding["provider_id"])
                if binding["model"] not in {*provider["models"], *saved.get("models", []), saved.get("model")}:
                    raise ApplicationError("invalid_model_settings", "请先在设置中添加该模型 ID。")
            if binding is not None and not self._has(binding):
                raise ApplicationError("model_not_configured", "请先为所选提供商及服务区域配置 API Key。")
            return binding

    def runtime(self, profile, binding, coding_binding=None):
        return self.runtime_factory(profile, self.validate(binding), coding_binding)
