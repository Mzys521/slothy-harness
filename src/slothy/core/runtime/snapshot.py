"""版本化 JSON 快照与存储接口；不序列化代码、SDK 或回调。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from json import dumps, loads
from math import isfinite
from typing import Any, Protocol

from slothy.core.events.base import RunCheckedError


class SnapshotError(RunCheckedError):
    error_code = "snapshot_error"


class SnapshotConflictError(SnapshotError):
    error_code = "snapshot_conflict"


def count(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SnapshotError(f"invalid {name}")
    return value


def seconds(value: Any, name: str) -> float:
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not isfinite(value) or value < 0
    ):
        raise SnapshotError(f"invalid {name}")
    return float(value)


def text_value(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SnapshotError(f"invalid {name}")
    return value


def json_copy(value: Any) -> Any:
    try:
        return loads(dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise SnapshotError("snapshot data must be finite JSON") from error


@dataclass(frozen=True)
class RuntimeSnapshot:
    _data: dict[str, Any] = field(repr=False)
    VERSION = 1

    def __post_init__(self):
        data = json_copy(self._data)
        if not isinstance(data, dict) or set(data) != {
            "version", "revision", "run", "context", "cursor", "tools",
            "policy", "model",
        }:
            raise SnapshotError("invalid snapshot fields")
        if count(data["version"], "version") != self.VERSION:
            raise SnapshotError("unsupported snapshot version")
        count(data["revision"], "revision")
        if any(not isinstance(data[key], dict) for key in (
            "run", "context", "cursor", "tools", "policy", "model",
        )):
            raise SnapshotError("invalid snapshot sections")
        text_value(data["run"].get("run_id"), "run_id")
        object.__setattr__(self, "_data", deepcopy(data))

    @property
    def run_id(self) -> str:
        return self._data["run"]["run_id"]

    @property
    def revision(self) -> int:
        return self._data["revision"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def to_json(self) -> str:
        return dumps(self._data, ensure_ascii=False, allow_nan=False)

    def with_revision(self, revision: int) -> RuntimeSnapshot:
        data = self.to_dict()
        data["revision"] = revision
        return RuntimeSnapshot(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSnapshot:
        return cls(data)

    @classmethod
    def from_json(cls, source: str) -> RuntimeSnapshot:
        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise SnapshotError("duplicate JSON field")
                result[key] = value
            return result

        try:
            return cls(loads(source, object_pairs_hook=object_pairs))
        except (TypeError, ValueError) as error:
            raise SnapshotError("invalid snapshot JSON") from error


class SnapshotStore(Protocol):
    def load(self, run_id: str) -> RuntimeSnapshot | None: ...

    def save(
        self, snapshot: RuntimeSnapshot, *, expected_revision: int,
    ) -> RuntimeSnapshot:
        """原子地比较版本并保存；存储错误必须传播，不能先执行再忽略保存。"""
        ...


class InMemorySnapshotStore:
    """单调用方内存实现；持久化及跨进程事务由 Infrastructure 提供。"""

    def __init__(self):
        self._snapshots: dict[str, RuntimeSnapshot] = {}

    def load(self, run_id: str) -> RuntimeSnapshot | None:
        snapshot = self._snapshots.get(run_id)
        return RuntimeSnapshot(snapshot.to_dict()) if snapshot is not None else None

    def save(self, snapshot, *, expected_revision):
        previous = self._snapshots.get(snapshot.run_id)
        actual = previous.revision if previous is not None else 0
        if actual != expected_revision:
            raise SnapshotConflictError("snapshot revision has changed")
        prepared = snapshot.with_revision(actual + 1)
        self._snapshots[snapshot.run_id] = prepared
        return RuntimeSnapshot(prepared.to_dict())
