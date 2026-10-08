"""运行器的上下文入口：追加领域消息，并准备下一次模型请求。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .contracts import Context
from .memory import InMemoryContext
from .messages import MessageRole

if TYPE_CHECKING:
    from slothy.core.events.emitter import EventEmitter
    from slothy.core.model.model_models import ModelResult
    from slothy.core.tools.tool_models import ToolResult


class Conversation:
    """一次 Run 的消息窗口；消息格式与压缩事件都封装在上下文模块。"""

    def __init__(
        self, window: Context, events: EventEmitter | None = None
    ) -> None:
        self._window = window
        self._events = events

    @property
    def messages(self) -> list[dict[str, Any]]:
        """兼容原有属性；新调用方使用 get_windowed_messages。"""
        return self.get_windowed_messages()

    def get_windowed_messages(self) -> list[dict[str, Any]]:
        """只通过 Context 契约读取请求窗口并转发本次压缩记录。"""
        from slothy.core.events.status import ContextCompressed

        messages = self._window.get_windowed_messages()
        record = self._window.last_compression
        if record is not None and self._events is not None:
            self._events.emit(
                ContextCompressed(
                    tokens_before=record.tokens_before,
                    tokens_after=record.tokens_after,
                    messages_removed=record.messages_removed,
                    messages_truncated=record.messages_truncated,
                    strategy=record.strategy,
                    preview=record.preview,
                )
            )
        report = getattr(self._window, "last_report", None)
        if isinstance(report, dict) and self._events is not None:
            from slothy.core.events import Metric
            for name, unit in (("input_tokens", "tokens"), ("memory_topk", "count"), ("summary_failures", "count")):
                value = report.get(name)
                if type(value) is int and value >= 0:
                    self._events.emit(Metric(name="context." + name, value=value, unit=unit))
        return messages

    @property
    def can_snapshot(self) -> bool:
        return all(callable(getattr(self._window, method, None))
                   for method in ("snapshot_state", "restore_state"))

    def snapshot_state(self) -> dict[str, Any]:
        from .contracts import ContextError

        if not self.can_snapshot:
            raise ContextError("注入的 Context 没有快照能力")
        return self._window.snapshot_state()

    def bind_request(self, definitions, tool_context) -> dict[str, Any]:
        """上下文自己的可选请求配置入口；旧 Context 不需要增加方法。"""
        bind = getattr(self._window, "bind_request", None)
        if callable(bind):
            bind(definitions, tool_context)
        return dict(getattr(self._window, "request_options", {}))

    def validate_pending_exchange(
        self, response: dict, index: int, results: list[str] | None = None,
    ) -> None:
        from .contracts import ContextError

        if not self.can_snapshot:
            return
        state = self.snapshot_state()
        messages = state.get("active") if state.get("kind") == "in_memory" else (
            state.get("messages") if state.get("kind") == "window" else None
        )
        if messages is None:
            validate = getattr(self._window, "validate_pending_exchange", None)
            if not callable(validate):
                raise ContextError("自定义快照 Context 必须校验未完成工具往返")
            if results is None:
                validate(response, index)
            else:
                # 保持旧自定义实现的二参数方法，新增实现显式声明结果校验能力。
                from .layered import LayeredContext
                if isinstance(self._window, LayeredContext):
                    validate(response, index, results)
                else:
                    validate(response, index)
            return
        tail = messages[-(index + 1):]
        assistant = {"role": "assistant", "content": response["text"]}
        if response["tool_calls"]:
            assistant["tool_calls"] = response["tool_calls"]
        if len(tail) != index + 1 or tail[0] != assistant:
            raise ContextError("快照游标与助手工具调用不匹配")
        if any(
            item.get("role") != "tool"
            or item.get("call_id") != call["call_id"]
            for item, call in zip(tail[1:], response["tool_calls"][:index])
        ):
            raise ContextError("快照游标与工具结果不匹配")
        if results is not None and (
            len(results) != index
            or any(item.get("content") != result
                   for item, result in zip(tail[1:], results))
        ):
            raise ContextError("快照上下文与已保存工具结果不匹配")

    def _append(
        self, message: str | ModelResult | ToolResult, call_id: str | None
    ) -> None:
        # 使用时再导入领域类型，避免事件数据类型初始化上下文包时形成循环。
        from slothy.core.model.model_models import ModelResult
        from slothy.core.tools.tool_models import ToolResult

        prepared: dict[str, Any]
        if isinstance(message, str):
            prepared = {"role": MessageRole.USER.value, "content": message}
        elif isinstance(message, ModelResult):
            prepared = {
                "role": MessageRole.ASSISTANT.value,
                "content": message.text or "",
            }
            if message.tool_calls:
                prepared["tool_calls"] = [
                    {
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in message.tool_calls
                ]
        elif isinstance(message, ToolResult):
            if not call_id:
                raise ValueError("工具结果必须关联 call_id")
            prepared = {
                "role": MessageRole.TOOL.value,
                "call_id": call_id,
                "content": message.to_model_output(),
            }
        else:
            raise TypeError("只接受用户输入、模型响应或工具结果")
        self._window.add(prepared)


def add(
    message: str | ModelResult | ToolResult,
    conversation: Conversation | None = None,
    *,
    call_id: str | None = None,
    window: Context | None = None,
    token_budget: int | None = None,
    events: EventEmitter | None = None,
) -> Conversation:
    """统一追加消息；首次调用创建窗口，后续调用复用返回的 Conversation。

    默认每次 Run 新建窗口；显式传入的窗口保持原有写入语义。只在读取
    ``conversation.get_windowed_messages()`` 时准备预算与压缩，不在追加时裁剪。
    """
    if conversation is None:
        if window is None:
            window = (
                InMemoryContext()
                if token_budget is None
                else InMemoryContext(token_budget=token_budget)
            )
        conversation = Conversation(window, events)
    elif window is not None or token_budget is not None or events is not None:
        raise ValueError("已有 Conversation 时不能重新配置窗口或事件")
    conversation._append(message, call_id)
    return conversation


def restore(
    data: dict[str, Any], *, window: Context | None = None,
    events: EventEmitter | None = None,
) -> Conversation:
    """恢复完整历史和活动窗口；摘要器与计数器由宿主重新注入。"""
    from .contracts import ContextError
    from .window import ContextWindow

    if window is None:
        if data.get("kind") not in {"in_memory", "window"}:
            raise ContextError("自定义 Context 快照需要重新注入实现")
        cls = InMemoryContext if data["kind"] == "in_memory" else ContextWindow
        window = cls(
            token_budget=data["token_budget"], system_prompt=data["system_prompt"],
        )
    restore_state = getattr(window, "restore_state", None)
    if not callable(restore_state):
        raise ContextError("注入的 Context 没有恢复能力")
    restore_state(data)
    return Conversation(window, events)
