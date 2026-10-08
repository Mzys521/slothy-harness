"""官方文本模型预设；接口地址只由宿主维护，不接收模型/页面的任意 URL。"""

from copy import deepcopy
import re


PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek", "default_model": "deepseek-flash",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "endpoints": [{"id": "standard", "label": "官方 API", "base_url": "https://api.deepseek.com"}],
        "documentation_url": "https://api-docs.deepseek.com/quick_start/pricing/",
        "key_url": "https://platform.deepseek.com/api_keys",
        "can_list_models": True,
    },
    "qwen": {
        "name": "Qwen · 通义千问", "default_model": "qwen-plus",
        "models": ["qwen-plus", "qwen-flash", "qwen-max", "qwen3-coder-plus", "qwen3-coder-flash"],
        "endpoints": [
            {"id": "china", "label": "中国内地 · 北京", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            {"id": "international", "label": "国际 · 新加坡", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"},
            {"id": "us", "label": "美国 · 弗吉尼亚", "base_url": "https://dashscope-us.aliyuncs.com/compatible-mode/v1"},
        ],
        "documentation_url": "https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope",
        "key_url": "https://bailian.console.aliyun.com/",
        "can_list_models": True,
    },
    "mimo": {
        "name": "MiMo · 小米", "default_model": "mimo-v2.5-pro",
        "models": ["mimo-v2.5-pro", "mimo-v2.5"],
        "endpoints": [{"id": "standard", "label": "官方 API", "base_url": "https://api.xiaomimimo.com/v1"}],
        "documentation_url": "https://platform.xiaomimimo.com/docs/en-US/usage-guide/passing-back-reasoning_content",
        "key_url": "https://platform.xiaomimimo.com/",
        "can_list_models": False,
    },
    "glm": {
        "name": "GLM · 智谱", "default_model": "glm-5",
        "models": ["glm-5", "glm-4.7", "glm-4.5-air"],
        "endpoints": [{"id": "standard", "label": "智谱开放平台 API", "base_url": "https://open.bigmodel.cn/api/paas/v4"}],
        "documentation_url": "https://docs.bigmodel.cn/cn/guide/models/text/glm-5",
        "key_url": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "can_list_models": False,
    },
}


def provider_catalog():
    return [{"id": key, **deepcopy(value)} for key, value in PROVIDERS.items()]


def validate_binding(value):
    if not isinstance(value, dict) or set(value) != {"provider_id", "endpoint_id", "model"}:
        raise ValueError("invalid_model_binding")
    provider_id, endpoint_id, model = value["provider_id"], value["endpoint_id"], value["model"]
    if not isinstance(provider_id, str) or provider_id not in PROVIDERS:
        raise ValueError("invalid_provider")
    if not isinstance(endpoint_id, str) or endpoint_id not in {item["id"] for item in PROVIDERS[provider_id]["endpoints"]}:
        raise ValueError("invalid_endpoint")
    validate_model(model)
    return deepcopy(value)


def validate_model(model):
    if (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model)
            or any(kind in model.lower() for kind in ("embedding", "rerank", "tts", "audio", "image", "video"))):
        raise ValueError("invalid_text_model")
    return model


def endpoint_url(binding):
    value = validate_binding(binding)
    return next(item["base_url"] for item in PROVIDERS[value["provider_id"]]["endpoints"] if item["id"] == value["endpoint_id"])
