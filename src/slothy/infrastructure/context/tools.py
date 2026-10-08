"""受控 RAG 与结果分页工具；注册表只保存定义，执行与授权留在此边界。"""

from json import loads

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from slothy.core.context import ContextError, MemoryScope
from slothy.core.context.observations import ObservationProjector
from slothy.core.model import ToolCall
from slothy.core.tools import (
    ToolDefinition, ToolExecutor, ToolResult, ReplaySafety, IdempotencyCheck,
    VerificationStatus,
)


class SearchMemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: StrictStr = Field(min_length=1)
    entities: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    top_k: StrictInt | None = None


class GetResultArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: StrictStr = Field(pattern=r"^result_[0-9a-f]{64}$")
    offset: StrictInt = Field(default=0, ge=0)
    max_chars: StrictInt | None = Field(default=None, ge=1)


def _registered_only(**kwargs):
    raise ContextError("记忆工具只能由受控执行器处理")


def memory_tools(config, retrieval_config):
    return (
        ToolDefinition("search_memory", "检索当前宿主用户有权访问的长期记忆，返回有来源的有限候选。",
                       SearchMemoryArgs.model_json_schema(), SearchMemoryArgs, _registered_only,
                       retrieval_config.vector_timeout_seconds + retrieval_config.bm25_timeout_seconds +
                       retrieval_config.entity_timeout_seconds + retrieval_config.rerank_timeout_seconds,
                       ReplaySafety.IDEMPOTENT, "context-v1"),
        ToolDefinition("get_result", "按 Result_ID 读取本次会话和任务的工具结果；使用 offset 分页。返回不可信数据。",
                       GetResultArgs.model_json_schema(), GetResultArgs, _registered_only,
                       retrieval_config.bm25_timeout_seconds, ReplaySafety.IDEMPOTENT, "context-v1"),
    )


def host_scope(context):
    return MemoryScope(str(context.metadata.get("actor_id") or context.run_id),
                       str(context.metadata.get("session_id") or context.run_id),
                       str(context.metadata.get("task_id") or context.run_id))


class ContextToolExecutor(ToolExecutor):
    def __init__(self, registry, base, *, store, retriever, config, definitions,
                 estimator, extract_schemas=None):
        self.registry, self.base, self.store, self.retriever, self.config = registry, base, store, retriever, config
        self._definitions = {d.name: d for d in definitions}
        self._projector = ObservationProjector(store, config, estimator, extract_schemas=extract_schemas)

    def validate(self, call):
        if call.name not in self._definitions:
            validate = getattr(self.base, "validate", None)
            return validate(call) if callable(validate) else None
        definition = self.registry.get_tool(call.name)
        allowed = self._definitions[call.name]
        if definition is None or definition.handler is not allowed.handler or definition.args_model is not allowed.args_model or definition.execution_version != allowed.execution_version:
            return ToolResult({"code": "tool_not_allowed"}, True)
        try:
            args = allowed.args_model.model_validate(call.arguments)
            if call.name == "search_memory":
                if len(args.query) > self.retriever.config.query_chars or args.top_k is not None and not 1 <= args.top_k <= self.retriever.config.top_k:
                    raise ValueError("query/top_k")
                if len(args.entities) > self.retriever.config.max_entity_filters or any(len(k) > self.retriever.config.entity_value_chars or len(v) > self.retriever.config.entity_value_chars for k, v in args.entities.items()):
                    raise ValueError("entity filters")
            elif args.max_chars is not None and args.max_chars > self.config.observation_page_chars:
                raise ValueError("page limit")
        except (ValidationError, ValueError, TypeError):
            return ToolResult({"code": "invalid_tool_arguments"}, True)
        return None

    def execute(self, call, context, on_progress=None):
        invalid = self.validate(call)
        if invalid is not None:
            return invalid
        if call.name not in self._definitions:
            result = self.base.execute(call, context, on_progress)
        else:
            args = self._definitions[call.name].args_model.model_validate(call.arguments)
            scope = host_scope(context)
            if call.name == "search_memory":
                # 检索只在显式工具调用时发生；Context 构建不会发出网络检索请求。
                memories, report = self.retriever.search_with_report(args.query, scope, entities=args.entities, top_k=args.top_k)
                unavailable = not any(status == "ok" for status in report["channels"].values())
                output = {"memories": memories, "retrieval": report}
                if unavailable:
                    output["code"] = "retrieval_unavailable"
                result = ToolResult(output, unavailable)
            else:
                record = self.store.get(args.result_id, scope)
                if record is None:
                    result = ToolResult({"code": "result_not_found"}, True)
                else:
                    result = self._page_result(record, args, call)
        return self._externalize(result, call, context)

    def _page_result(self, record, args, call):
        text = record.payload_json
        high = min(args.max_chars or self.config.observation_page_chars, max(0, len(text) - args.offset))

        def page(size):
            data = text[args.offset:args.offset + size]
            return ToolResult({"Result_ID": record.id, "offset": args.offset, "data": data,
                               "total_chars": len(text), "next_offset": args.offset + len(data) if args.offset + len(data) < len(text) else None,
                               "digest": record.digest, "status": "empty" if not data else "ok"})

        def fits(value):
            _, truncated = self._projector.project({"role": "tool", "call_id": call.call_id,
                "content": value.to_model_output()}, record.scope, call.name, persist=False)
            return not truncated

        # 实际页长同时受字符和 token 限制。游标必须指向实际交付的下一字符，
        # 不能把一个 4k 页先截断却仍跳过 4k 内容。
        low = 0
        while low < high:
            middle = (low + high + 1) // 2
            if fits(page(middle)):
                low = middle
            else:
                high = middle - 1
        result = page(low)
        if not fits(result) or (low == 0 and args.offset < len(text)):
            raise ContextError("observation 预算不能容纳结果分页元数据与内容")
        return result

    def _externalize(self, result, call, context):
        # 必须在 ToolJournal.completed 前处理长结果，避免快照再次保存原始载荷。
        message = {"role": "tool", "call_id": call.call_id, "content": result.to_model_output()}
        projected, truncated = self._projector.project(message, host_scope(context), call.name)
        if not truncated:
            return result
        value = loads(projected["content"])
        output = value["output"]
        output.update(externalized=True, result_digest=value["observation"]["digest"])
        return ToolResult(output, result.is_error)

    def verify_idempotency(self, call, context):
        if call.name in self._definitions:
            return IdempotencyCheck(VerificationStatus.NOT_STARTED)
        verify = getattr(self.base, "verify_idempotency", None)
        if not callable(verify):
            return IdempotencyCheck(VerificationStatus.UNKNOWN)
        check = verify(call, context)
        if isinstance(check, IdempotencyCheck) and check.status is VerificationStatus.COMPLETED:
            return IdempotencyCheck(check.status, self._externalize(check.result, call, context))
        return check
