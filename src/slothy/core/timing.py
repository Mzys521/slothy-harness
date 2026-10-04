"""时间度量辅助：统一以毫秒表达耗时。"""

from time import monotonic


def elapsed_ms(started_at: float, ended_at: float | None = None) -> float:
    """返回 ``started_at`` 到 ``ended_at``（默认当前时刻）的毫秒数。

    时钟回退或完全相同的时间点都返回 ``0.0``，不会产生负的耗时。
    """
    end = monotonic() if ended_at is None else ended_at
    return max(0.0, (end - started_at) * 1000)
