"""一次 Run 的模型调用入口，封装流式、错误分类与用量累计。"""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from slothy.core.events import (
    LLMTimeout,
    LLMTimeoutError,
    ModelError,
    ModelRequestStart,
    ModelResponded,
    TokenChunk,
    TokenUsage,
    describe_error,
)
from slothy.core.events.emitter import EventEmitter

from .model_models import ModelResult, ModelUsage
from .provider import ModelProvider
from slothy.core.policy.session import PolicySession


class ModelSession:
    """只通过 model_call 调用提供方；累计用量与分片序号不跨 Run。"""

    def __init__(
        self,
        model: ModelProvider,
        events: EventEmitter,
        check_active: Callable[[], None],
        policy: PolicySession | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> None:
        self._model = model
        self._events = events
        self._check_active = check_active
        self._usage = ModelUsage()
        self._chunk_index = 0
        self._policy = policy
        self._checkpoint = checkpoint
        self._attempts = 0
        self._elapsed_seconds = 0.0

    def snapshot_state(self) -> dict:
        return {
            "usage": vars(self._usage).copy(), "chunk_index": self._chunk_index,
            "attempts": self._attempts, "elapsed_seconds": self._elapsed_seconds,
        }

    def restore_state(self, data: dict) -> None:
        from slothy.core.runtime.snapshot import SnapshotError, count, seconds

        if set(data) != {"usage", "chunk_index", "attempts", "elapsed_seconds"}:
            raise SnapshotError("invalid model snapshot")
        if not isinstance(data["usage"], dict) or set(data["usage"]) != {
            "total_tokens", "prompt_tokens", "completion_tokens",
        }:
            raise SnapshotError("invalid model usage")
        self._usage = ModelUsage(**{
            key: count(value, key) for key, value in data["usage"].items()
        })
        self._chunk_index = count(data["chunk_index"], "chunk_index")
        self._attempts = count(data["attempts"], "model_attempts")
        self._elapsed_seconds = seconds(data["elapsed_seconds"], "model_elapsed")

    def model_call(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelResult:
        """提交请求，记录响应，再检查取消/时限并累计用量。

        检查发生在 ModelResponded 与 TokenUsage 之间，保持既有取消事件顺序。
        """
        # 上下文构建可能调用同步摘要器；在模型请求前重新检查取消和时限。
        self._check_active()
        started_at = self._events.clock()
        logical_start = started_at - self._elapsed_seconds
        streamed = False

        def attempt(timeout: float | None) -> ModelResult:
            nonlocal started_at
            self._attempts += 1
            started_at = self._events.clock()
            self._events.emit(
                ModelRequestStart(message_count=len(messages), tool_count=len(tools))
            )
            if self._checkpoint is not None:
                self._checkpoint()
            active = True

            def on_chunk(text: str) -> None:
                nonlocal streamed
                if active:
                    streamed = True
                    self._on_chunk(text)

            options: dict[str, Any] = {
                "tools": deepcopy(tools),
                "on_chunk": on_chunk if self._events.enabled else None,
            }
            if timeout is not None:
                options["timeout"] = timeout
            try:
                return self._model.generate(deepcopy(messages), **options)
            finally:
                active = False
                self._elapsed_seconds = self._events.clock() - logical_start

        def on_failure(error: Exception) -> None:
            kind = LLMTimeout if isinstance(error, LLMTimeoutError) else ModelError
            self._events.emit(kind(
                duration_ms=self._events.elapsed(started_at),
                error=describe_error(error),
            ))

        if self._policy is not None:
            response = self._policy.invoke(
                "model", attempt, on_failure, streamed=lambda: streamed,
                start_attempt=self._attempts + 1,
                elapsed_seconds=self._elapsed_seconds,
            )
        else:
            try:
                response = attempt(None)
            except Exception as error:
                on_failure(error)
                raise

        self._events.emit(
            ModelResponded(
                duration_ms=self._events.elapsed(started_at),
                text_length=len(response.text or ""),
                tool_call_count=len(response.tool_calls),
                usage=response.usage,
            )
        )
        self._check_active()
        self._usage = self._usage + response.usage
        self._events.emit(TokenUsage(usage=response.usage, cumulative=self._usage))
        self._attempts = 0
        self._elapsed_seconds = 0.0
        return response

    def _on_chunk(self, text: str) -> None:
        self._events.emit(TokenChunk(index=self._chunk_index, text=text))
        self._chunk_index += 1
        if self._checkpoint is not None:
            self._checkpoint()
