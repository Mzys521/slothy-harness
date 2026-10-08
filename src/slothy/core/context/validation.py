"""消息与工具往返校验；旧适配器和分层引擎共用。"""

from copy import deepcopy
from json import dumps
from typing import Any

from .contracts import ContextError
from .messages import MessageRole


def validate_message(message: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise TypeError("上下文消息必须是字典")
    if not isinstance(message.get("role"), str) or message["role"] not in {r.value for r in MessageRole}:
        raise ContextError("不支持的上下文消息角色")
    if not isinstance(message.get("content", ""), str):
        raise ContextError("上下文消息内容必须是字符串")
    if message["role"] == "tool" and (not isinstance(message.get("call_id"), str) or not message["call_id"]):
        raise ContextError("工具结果必须携带调用标识")
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list) or (calls and message["role"] != "assistant"):
        raise ContextError("tool_calls 必须是助手消息中的列表")
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("call_id") or call.get("id"), str) or not (call.get("call_id") or call.get("id")):
            raise ContextError("工具调用必须携带调用标识")
    try:
        dumps(message, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ContextError("上下文消息必须能编码为 JSON") from error
    prepared = deepcopy(message)
    prepared.setdefault("content", "")
    return prepared


def exchange_groups(messages, *, strict=True):
    groups = []
    for message in messages:
        if message["role"] == "tool":
            if not groups or groups[-1][0]["role"] != "assistant":
                raise ContextError("工具结果缺少对应的助手调用")
            groups[-1].append(message)
        else:
            groups.append([message])
    if strict:
        for group in groups:
            calls = group[0].get("tool_calls", [])
            expected = [c.get("call_id") or c.get("id") for c in calls]
            received = [m.get("call_id") for m in group[1:]]
            if len(set(expected)) != len(expected) or sorted(expected) != sorted(received):
                raise ContextError("助手工具调用与结果未完整配对")
    return groups


def count_tokens(estimator, messages):
    value = estimator.estimate(messages)
    if type(value) is not int or value < 0:
        raise ContextError("Token 计数器必须返回非负整数")
    return value
