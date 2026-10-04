"""API 请求 DTO；客户端不能注入策略、模型、原始快照或审批身份。"""

from dataclasses import dataclass

from slothy.application.errors import ApplicationError


def _fields(payload: object, required: set[str], optional=frozenset()):
    if type(payload) is not dict or not required <= payload.keys() or (
        payload.keys() - required - optional
    ):
        raise ApplicationError("invalid_request", "请求字段缺失或包含未知字段。")
    return payload


def _text(value: object, name: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ApplicationError("invalid_request", f"{name} 必须为非空且长度受限的字符串。")
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApplicationError("invalid_request", f"{name} 必须为范围内的整数。")
    return value


@dataclass(frozen=True)
class CreateRunRequest:
    user_input: str

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, {"user_input"})
        return cls(_text(data["user_input"], "user_input", 100_000))


@dataclass(frozen=True)
class RunRequest:
    run_id: str

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, {"run_id"})
        return cls(_text(data["run_id"], "run_id"))


@dataclass(frozen=True)
class ResumeRunRequest:
    run_id: str
    expected_revision: int

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, {"run_id", "expected_revision"})
        return cls(
            _text(data["run_id"], "run_id"),
            _integer(data["expected_revision"], "expected_revision", 1, 2**63 - 1),
        )


@dataclass(frozen=True)
class ApprovalCommandRequest:
    run_id: str
    request_id: str
    expected_revision: int

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, {"run_id", "request_id", "expected_revision"})
        return cls(
            _text(data["run_id"], "run_id"),
            _text(data["request_id"], "request_id"),
            _integer(data["expected_revision"], "expected_revision", 1, 2**63 - 1),
        )


@dataclass(frozen=True)
class ListRunsRequest:
    offset: int = 0
    limit: int = 100

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, set(), {"offset", "limit"})
        return cls(
            _integer(data.get("offset", 0), "offset", 0, 2**31 - 1),
            _integer(data.get("limit", 100), "limit", 1, 200),
        )


@dataclass(frozen=True)
class EventsRequest:
    run_id: str
    after: int = 0
    limit: int = 100

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, {"run_id"}, {"after", "limit"})
        return cls(
            _text(data["run_id"], "run_id"),
            _integer(data.get("after", 0), "after", 0, 2**63 - 1),
            _integer(data.get("limit", 100), "limit", 1, 200),
        )


@dataclass(frozen=True)
class UnsubscribeRequest:
    run_id: str
    subscription_id: str

    @classmethod
    def parse(cls, payload: object):
        data = _fields(payload, {"run_id", "subscription_id"})
        return cls(
            _text(data["run_id"], "run_id"),
            _text(data["subscription_id"], "subscription_id"),
        )
