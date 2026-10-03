"""面向提供方中立的核心模型契约的 MiMo 适配器。"""

import json
import os
from typing import Any

from openai import OpenAI

from slothy.core.model import ModelProvider, ModelResult, ModelUsage, ToolCall


class MimoProvider(ModelProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        resolved_key = os.getenv("MIMO_API_KEY") or api_key or ""
        resolved_url = os.getenv("MIMO_BASE_URL") or base_url or ""
        resolved_model = os.getenv("MIMO_MODEL") or model or ""
        super().__init__(resolved_key, resolved_url, resolved_model)
        self.client = OpenAI(api_key=resolved_key, base_url=resolved_url)

    def generate(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResult:
        """在 SDK 边界处转换核心层消息与工具定义。"""
        options = dict(kwargs)
        definitions = options.pop("tools", None) or []
        if definitions:
            options["tools"] = [
                {"type": "function", "function": definition}
                for definition in definitions
            ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[self._to_chat_message(message) for message in messages],
            **options,
        )
        message = response.choices[0].message
        calls = [
            ToolCall(
                call_id=call.id,
                name=call.function.name,
                arguments=self._parse_arguments(call.function.arguments),
            )
            for call in message.tool_calls or []
        ]
        usage = response.usage
        return ModelResult(
            text=message.content or "",
            tool_calls=calls,
            usage=ModelUsage(
                total_tokens=usage.total_tokens if usage else 0,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ),
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
