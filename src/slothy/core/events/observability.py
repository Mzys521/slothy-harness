"""观测事件：令牌用量与通用度量。

这两个事件面向日志、界面和后续的持久化，不改变运行时行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from slothy.core.model import ModelUsage

from .base import RunEvent


@dataclass
class TokenUsage(RunEvent):
    """模型报告的令牌用量。

    ``usage`` 是本次模型调用的用量，``cumulative`` 是本次 Run 到当前为止的
    累计用量；两者都由提供方报告，核心层不做估算。
    """

    EVENT_TYPE = "run.observability.token_usage"

    usage: ModelUsage = field(default_factory=ModelUsage)
    cumulative: ModelUsage = field(default_factory=ModelUsage)


@dataclass
class Metric(RunEvent):
    """通用数值度量，供可观测性使用。

    ``name`` 使用 ``域.指标`` 形式，当前由运行时观测模块发出的指标见
    ``docs/runtime-events.md``。
    """

    EVENT_TYPE = "run.observability.metric"

    name: str = ""
    value: float = 0.0
    unit: str = ""
