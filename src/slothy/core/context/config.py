"""上下文预算与降级配置。默认值集中在配置，算法不持有隐藏预算。"""

from dataclasses import dataclass, fields
from math import isfinite

DEFAULT_TOKEN_BUDGET = 8192
PREVIEW_LIMIT = 120


@dataclass(frozen=True)
class ContextConfig:
    model_window: int = 32768
    output_reserve: int = 4096
    safety_margin: int = 512
    system_prompt: int = 4096
    tool_schemas: int = 2048
    tool_schema_overhead_tokens: int = 32
    task_state: int = 2048
    long_term_memory: int = 4096
    working_memory: int = 6144
    user_input_buffer: int = 2048
    recent_turns: int = 6
    summary_tokens: int = 1024
    summary_input_tokens: int = 6144
    summary_timeout_seconds: float = 15.0
    observation_tokens: int = 512
    observation_chars: int = 2048
    observation_page_chars: int = 4096
    history_messages: int = 2000

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "summary_timeout_seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                    raise ValueError(f"{item.name} 必须是有限正数")
            elif type(value) is not int or value < (0 if item.name == "safety_margin" else 1):
                raise ValueError(f"{item.name} 必须是有效整数")
        if self.input_budget < 1:
            raise ValueError("model_window 必须大于 output_reserve + safety_margin")

    @property
    def input_budget(self) -> int:
        return self.model_window - self.output_reserve - self.safety_margin

    @classmethod
    def for_input_budget(cls, token_budget: int, **overrides):
        """旧入口的 token_budget 仍表示输入上限；输出空间另行预留。"""
        if type(token_budget) is not int or token_budget < 1:
            raise ValueError("token_budget 必须是正整数")
        defaults = cls()
        output = overrides.pop("output_reserve", defaults.output_reserve)
        margin = overrides.pop("safety_margin", defaults.safety_margin)
        return cls(model_window=token_budget + output + margin,
                   output_reserve=output, safety_margin=margin, **overrides)
