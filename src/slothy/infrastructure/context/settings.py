"""从环境加载非密钥配置；密钥仅由模型适配器在认证边界读取。"""

from dataclasses import fields
import os

from slothy.core.context import ContextConfig, RetrievalConfig


def load_config(cls, prefix):
    values = {}
    defaults = cls()
    for field in fields(cls):
        raw = os.environ.get(prefix + field.name.upper())
        if raw is not None and raw.strip():
            try:
                values[field.name] = int(raw) if type(getattr(defaults, field.name)) is int else float(raw)
            except ValueError:
                raise ValueError(f"配置 {prefix}{field.name.upper()} 不是有效数字") from None
    return cls(**values)


def context_config():
    return load_config(ContextConfig, "SLOTHY_CONTEXT_")


def retrieval_config():
    return load_config(RetrievalConfig, "SLOTHY_RAG_")
