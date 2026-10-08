"""四家官方 Chat Completions 适配：流式、工具调用与安全错误分类。"""

from contextlib import suppress
from openai import APIConnectionError, APIStatusError, APITimeoutError, DefaultHttpxClient, OpenAI

from slothy.core.events import LLMTimeoutError, RunCheckedError, TransientModelError
from slothy.core.model import ModelProvider
from .catalog import endpoint_url, validate_binding, validate_model
from .mimo_provider import MimoProvider


class ConfiguredModelError(RunCheckedError):
    def __init__(self, code, message):
        self.error_code = code
        super().__init__(message)


def client_factory(**kwargs):
    return OpenAI(**kwargs, http_client=DefaultHttpxClient(follow_redirects=False))


def safe_error(error):
    if isinstance(error, (APITimeoutError, LLMTimeoutError)):
        return LLMTimeoutError("模型请求超时。")
    if isinstance(error, (APIConnectionError, TransientModelError)):
        return TransientModelError("模型连接失败或服务暂时不可用。")
    if isinstance(error, APIStatusError):
        if error.status_code in (401, 403):
            return ConfiguredModelError("model_authentication_error", "API Key 无效或没有访问权限。")
        if error.status_code == 404:
            return ConfiguredModelError("model_not_found", "模型不存在或当前账号不可用，请检查模型 ID。")
        if error.status_code == 429 or error.status_code >= 500:
            return TransientModelError("模型服务限流或暂时不可用。")
        return ConfiguredModelError("model_request_error", "提供商拒绝了请求，请检查模型是否支持文本生成和工具调用。")
    return ConfiguredModelError("model_response_error", "模型返回了无法处理的响应。")


class CompatibleChatProvider(MimoProvider):
    def __init__(self, binding, credentials, actor_id, *, sdk_factory=None):
        self.binding = validate_binding(binding)
        ModelProvider.__init__(self, None, endpoint_url(self.binding), self.binding["model"])
        self._credentials, self._actor_id = credentials, actor_id
        self._sdk_factory = sdk_factory or client_factory
        self.client = None

    def _client(self):
        try:
            key = self._credentials.get(self._actor_id, self.binding["provider_id"], self.binding["endpoint_id"])
        except Exception:
            raise ConfiguredModelError("model_credentials_unavailable", "本机凭据无法读取，请检查设置。") from None
        if not key:
            raise ConfiguredModelError("model_not_configured", "该任务的提供商尚未配置 API Key，请在设置中添加。")
        return self._sdk_factory(api_key=key, base_url=self.base_url, max_retries=0, timeout=30)

    def generate(self, messages, **kwargs):
        # Core 不保存 reasoning_content；明确关闭供应商默认的深度思考，保持工具往返完整。
        options = dict(kwargs)
        provider_id = self.binding["provider_id"]
        if provider_id in ("deepseek", "mimo") or (provider_id == "glm" and self.model.startswith(("glm-5", "glm-4.7", "glm-4.6", "glm-4.5"))):
            options["extra_body"] = {"thinking": {"type": "disabled"}}
        elif provider_id == "qwen" and "coder" not in self.model and self.model != "qwen-max":
            options["extra_body"] = {"enable_thinking": False}
        try:
            self.client = self._client()
            return super().generate(messages, **options)
        except (APIStatusError, APIConnectionError, APITimeoutError, LLMTimeoutError, TransientModelError,
                ValueError, TypeError, IndexError, AttributeError) as error:
            raise safe_error(error) from None
        finally:
            if self.client is not None:
                with suppress(Exception):
                    self.client.close()
                self.client = None

    @staticmethod
    def _collect_tool_calls(fragments, deltas):
        # SDK 流式分片是增量；相邻的相同字符也是有效参数，不能按后缀去重。
        for delta in deltas or ():
            fragment = fragments.setdefault(delta.index or 0, {"call_id": "", "name": "", "arguments": ""})
            fragment["call_id"] += getattr(delta, "id", None) or ""
            function = getattr(delta, "function", None)
            if function is not None:
                fragment["name"] += getattr(function, "name", None) or ""
                fragment["arguments"] += getattr(function, "arguments", None) or ""

    def test_connection(self):
        limit = {"max_completion_tokens": 8} if self.binding["provider_id"] == "mimo" else {"max_tokens": 8}
        self.generate([{"role": "user", "content": "Reply OK."}], timeout=15, **limit)

    def list_models(self):
        client = None
        try:
            client = self._client()
            page = client.models.list(timeout=15)
            models = []
            # 不迭代 SDK 的自动分页，限制一次响应规模。
            for item in list(page.data)[:256]:
                try:
                    model = validate_model(item.id)
                except (ValueError, AttributeError):
                    continue
                if model not in models:
                    models.append(model)
            if not models:
                raise ConfiguredModelError("model_catalog_empty", "提供商没有返回文本模型列表，可直接添加模型 ID。")
            return models
        except (APIStatusError, APIConnectionError, APITimeoutError, ValueError, TypeError, AttributeError) as error:
            raise safe_error(error) from None
        finally:
            if client is not None:
                with suppress(Exception):
                    client.close()
