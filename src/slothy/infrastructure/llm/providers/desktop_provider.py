"""延迟创建真实文本模型，未配置时不会悄悄换成演示模型。"""

import os

from slothy.core.context import ContextError
from slothy.core.model import ModelProvider
from slothy.infrastructure.context.dashscope import DashScopeChatProvider
from .mimo_provider import MimoProvider


def configured(value):
    return bool(value and value.strip() and not value.strip().startswith("<"))


def model_status():
    dashscope = all(configured(os.environ.get(name)) for name in (
        "DASHSCOPE_CHAT_MODEL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL_WITH_OPENAI"))
    mimo = all(configured(os.environ.get(name)) for name in ("MIMO_MODEL", "MIMO_API_KEY", "MIMO_BASE_URL"))
    provider = "dashscope" if dashscope else "mimo" if mimo else None
    model = os.environ.get("DASHSCOPE_CHAT_MODEL" if dashscope else "MIMO_MODEL", "") if provider else None
    if model and any(part in model.lower() for part in ("embedding", "rerank")):
        provider = model = None
    return {"configured": provider is not None, "provider": provider, "name": model}


class DesktopModelProvider(ModelProvider):
    def __init__(self):
        self._status = model_status()
        super().__init__(None, None, self._status["name"])
        self._provider = None

    def generate(self, messages, **kwargs):
        if not self._status["configured"]:
            raise ContextError("请在宿主环境配置文本模型，embedding 不能生成回答。")
        if self._provider is None:
            self._provider = DashScopeChatProvider() if self._status["provider"] == "dashscope" else MimoProvider()
        return self._provider.generate(messages, **kwargs)
