"""面向提供方中立的核心模型契约的 MiMo 适配器。

支持两种响应方式：默认一次性返回完整响应；运行器传入 ``on_chunk`` 时改用流式
请求，逐段回调文本增量，并在流结束时返回同样的 :class:`ModelResult`。
"""

import json
import os
from typing import Any, Callable

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall
from slothy.core.events import LLMTimeoutError, TransientModelError


class MimoProvider(ModelProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        # api_key 参数保留签名兼容，但认证值只从环境读取。
        resolved_key = os.getenv("MIMO_API_KEY") or ""
        resolved_url = os.getenv("MIMO_BASE_URL") or base_url or ""
        resolved_model = os.getenv("MIMO_MODEL") or model or ""
        if any(kind in resolved_model.lower() for kind in ("embedding", "rerank")):
            raise ValueError("文本生成不能使用 embedding 或 rerank 模型")
        super().__init__(None, resolved_url, resolved_model)
        self.client = OpenAI(
            api_key=resolved_key, base_url=resolved_url, max_retries=0
        )

    def generate(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResult:
        """在 SDK 边界处转换核心层消息与工具定义。

        运行器会传入可选的 ``on_chunk``：提供该回调时改用流式请求并逐段回调；
        未提供时保持一次性请求，两者返回相同的核心层结果。
        """
        options = dict(kwargs)
        on_chunk = options.pop("on_chunk", None)
        definitions = options.pop("tools", None) or []
        if definitions:
            options["tools"] = [
                {"type": "function", "function": definition}
                for definition in definitions
            ]

        try:
            if on_chunk is None:
                return self._generate_once(messages, options)
            return self._generate_stream(messages, options, on_chunk)
        except APITimeoutError as error:
            raise LLMTimeoutError("模型请求超时") from error
        except APIConnectionError as error:
            raise TransientModelError("模型连接失败") from error
        except APIStatusError as error:
            if error.status_code == 429 or error.status_code >= 500:
                raise TransientModelError("模型服务暂时不可用") from error
            raise

    def _generate_once(
        self, messages: list[dict[str, Any]], options: dict[str, Any]
    ) -> ModelResult:
        """一次性请求并转换完整响应。"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[self._to_chat_message(message) for message in messages],
            **options,
        )
        message = response.choices[0].message
        return ModelResult(
            text=message.content or "",
            tool_calls=self._to_tool_calls(message.tool_calls),
            usage=self._to_usage(response.usage),
        )

    def _generate_stream(
        self,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
        on_chunk: Callable[[str], None],
    ) -> ModelResult:
        """流式请求：逐段回调文本增量，并按调用下标拼装工具调用。"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[self._to_chat_message(message) for message in messages],
            stream=True,
            stream_options={"include_usage": True},
            **options,
        )
        text_parts: list[str] = []
        fragments: dict[int, dict[str, Any]] = {}
        usage = ModelUsage()
        try:
            for chunk in stream:
                reported = getattr(chunk, "usage", None)
                if reported is not None:
                    usage = self._to_usage(reported)
                if not chunk.choices:
                    # 带 include_usage 的最后一个分片只包含用量。
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text_parts.append(delta.content)
                    on_chunk(delta.content)
                self._collect_tool_calls(fragments, getattr(delta, "tool_calls", None))
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

        return ModelResult(
            text="".join(text_parts),
            tool_calls=self._assemble_tool_calls(fragments),
            usage=usage,
        )

    @staticmethod
    def _collect_tool_calls(
        fragments: dict[int, dict[str, Any]], deltas: Any
    ) -> None:
        """累积流式工具调用分片。

        调用标识与名称通常只出现在第一段，参数按顺序分段到达，因此参数逐段拼接；
        个别提供方会重复下发同一段，此时跳过重复内容而不是拼接两次。
        """
        for delta in deltas or ():
            index = delta.index or 0
            fragment = fragments.setdefault(
                index, {"call_id": "", "name": "", "arguments": ""}
            )
            if not fragment["call_id"]:
                fragment["call_id"] = getattr(delta, "id", None) or ""
            if not fragment["name"]:
                fragment["name"] = delta.function.name or ""
            arguments = delta.function.arguments or ""
            if arguments and not fragment["arguments"].endswith(arguments):
                fragment["arguments"] += arguments

    def _assemble_tool_calls(
        self, fragments: dict[int, dict[str, Any]]
    ) -> list[ToolCall]:
        """把累积的分片转换为按下标排序的工具调用。"""
        return [
            ToolCall(
                call_id=fragment["call_id"] or f"call-{index}",
                name=fragment["name"],
                arguments=self._parse_arguments(fragment["arguments"]),
            )
            for index, fragment in sorted(fragments.items())
        ]

    def _to_tool_calls(self, calls: Any) -> list[ToolCall]:
        """转换一次性响应中的工具调用。"""
        return [
            ToolCall(
                call_id=call.id,
                name=call.function.name,
                arguments=self._parse_arguments(call.function.arguments),
            )
            for call in calls or []
        ]

    @staticmethod
    def _to_usage(usage: Any) -> ModelUsage:
        """转换提供方上报的令牌用量；未上报时返回零用量。"""
        if usage is None:
            return ModelUsage()
        return ModelUsage(
            total_tokens=usage.total_tokens,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

    @staticmethod
    def _parse_arguments(raw: str) -> dict[str, Any]:
        arguments = json.loads(raw)
        if not isinstance(arguments, dict):
            raise ValueError("Tool call arguments must be a JSON object")
        return arguments

    @staticmethod
    def _to_chat_message(message: dict[str, Any]) -> dict[str, Any]:
        role = message["role"]
        if role in {"system", "developer", "user"}:
            return {"role": role, "content": message["content"]}
        if role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message["call_id"],
                "content": message["content"],
            }
        if role == "assistant":
            converted: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content") or None,
            }
            calls = message.get("tool_calls") or []
            if calls:
                converted["tool_calls"] = [
                    {
                        "id": call["call_id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for call in calls
                ]
            return converted
        raise ValueError(f"Unsupported message role: {role}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    provider = MimoProvider()
    print(provider.generate([{"role": "user", "content": "请你为我计算1+1000"}]))
