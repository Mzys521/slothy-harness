"""生产上下文：四层、XML 信任边界、预算降级和外化 observation。"""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from json import loads

from .config import ContextConfig
from .contracts import ContextBudgetExceededError, ContextError
from .estimator import HeuristicTokenEstimator
from .observations import MemoryScope, ObservationProjector
from .prompt import FINAL_REMINDER, SYSTEM_GUARD, assemble, json_text, section
from .records import CompressionRecord
from .reduction import WindowReducer, fit_text
from .task_state import TaskState
from .validation import count_tokens, exchange_groups, validate_message


class LayeredContext:
    """实现现有 Context 契约；外部依赖均为宿主注入的接口。

    XML 工作记忆保存完整调用/结果数据对，不伪造原生 tool 消息。这样 summary
    与历史工具结果也遵守数据边界；当前模型仍可通过 tools 参数发起 Function Calling。
    实例属于单一 Run，宿主负责串行访问。
    """

    def __init__(self, *, store, config=None, estimator=None, system_prompt="",
                 summarizer=None, scope=None, task_state=None, extract_schemas=None,
                 observer=None, clock=None):
        self.config = config if config is not None else ContextConfig()
        if not isinstance(self.config, ContextConfig):
            raise TypeError("config 必须是 ContextConfig")
        if not isinstance(system_prompt, str):
            raise TypeError("system_prompt 必须是字符串")
        if summarizer is not None and not callable(summarizer):
            raise TypeError("summarizer 必须可调用")
        self.token_budget, self.estimator = self.config.input_budget, estimator or HeuristicTokenEstimator()
        self._system_prompt, self._summarizer = system_prompt, summarizer
        self._scope = scope
        self._state = TaskState.parse((task_state or TaskState()).to_dict())
        self._schemas, self._active, self._memories, self._archives = [], [], [], []
        self._recent_memory_ids = []
        self._summary = None
        self._last_compression, self._last_report = None, None
        self._pending_truncated = 0
        self._observer, self._clock = observer, clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._projector = ObservationProjector(store, self.config, self.estimator,
                                             extract_schemas=extract_schemas, clock=self._clock)
        self._cache_key, self._cache = None, None

    @property
    def scope(self):
        return self._scope

    @property
    def request_options(self):
        return {"max_tokens": self.config.output_reserve}

    def bind_request(self, schemas, tool_context):
        """由 Context 入口接收宿主范围与定义，不能由模型参数指定 owner。"""
        if not isinstance(schemas, list) or any(not isinstance(d, dict) or not isinstance(d.get("name"), str) for d in schemas):
            raise ContextError("工具定义必须来自注册表")
        metadata = tool_context.metadata
        scope = MemoryScope(str(metadata.get("actor_id") or tool_context.run_id),
                            str(metadata.get("session_id") or tool_context.run_id),
                            str(metadata.get("task_id") or tool_context.run_id))
        if self._scope is not None and self._scope != scope:
            raise ContextError("上下文的宿主范围与运行不匹配")
        self._scope, self._schemas = scope, deepcopy(schemas)
        if self._state.task_id == "unbound":
            self._state = replace(self._state, task_id=scope.task_id)
        elif self._state.task_id != scope.task_id:
            raise ContextError("任务状态与宿主任务范围不匹配")

    def set_task_state(self, state):
        parsed = TaskState.parse(state.to_dict() if isinstance(state, TaskState) else state)
        if self._scope is not None and parsed.task_id != self._scope.task_id:
            raise ContextError("不能改写宿主任务标识")
        self._state = parsed

    def set_memories(self, memories):
        """接收已授权检索工具的候选；绝不升级为 system 消息。"""
        self._memories = self._validate_memories(memories)

    def set_recent_memories(self, memories):
        """宿主为新 Run 注入已完成历史；后续检索不会抹掉上一条提问。"""
        self.set_memories(memories)
        self._recent_memory_ids = [m["id"] for m in self._memories]

    @staticmethod
    def _validate_memories(memories):
        if not isinstance(memories, list):
            raise ContextError("长期记忆必须是列表")
        prepared, seen = [], set()
        for item in memories:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
                raise ContextError("长期记忆记录无效")
            if item["id"] not in seen:
                seen.add(item["id"])
                # 限定可进入 Prompt 的字段；不接收 role / system 指令字段。
                prepared.append({k: deepcopy(item[k]) for k in ("id", "text", "source", "created_at", "score", "entities") if k in item})
        json_text(prepared)
        return prepared

    def add(self, message):
        prepared = validate_message(message)
        if prepared["role"] == "system":
            raise ContextError("系统指令只能通过宿主构造参数配置")
        if prepared["role"] == "tool":
            if self._scope is None:
                raise ContextError("工具结果必须先绑定宿主范围")
            calls = next((m.get("tool_calls", []) for m in reversed(self._active) if m.get("tool_calls")), [])
            call = next((c for c in calls if (c.get("call_id") or c.get("id")) == prepared["call_id"]), None)
            if call is None:
                raise ContextError("工具结果与当前请求未配对")
            name = (call.get("function") or call).get("name", "unknown")
            original = prepared["content"]
            prepared, truncated = self._projector.project(prepared, self._scope, name)
            prepared["source_digest"] = self._projector.digest(original)
            self._pending_truncated += int(truncated)
            # 检索必须作为工具调用到达；只有已登记名称且成功的结果可成为长期记忆。
            if name == "search_memory" and any(d["name"] == name for d in self._schemas):
                recent = [m for m in self._memories if m["id"] in self._recent_memory_ids]
                self._memories = recent
                try:
                    reference = loads(prepared["content"])["observation"]["Result_ID"]
                    stored = self._projector.store.get(reference, self._scope)
                    result = loads(stored.payload_json)
                    if result.get("is_error") is not True:
                        self.set_memories(recent + result["output"]["memories"])
                except (ValueError, TypeError, KeyError):
                    pass
        prepared["context_time"] = self._clock()
        self._active.append(prepared)
        if prepared["role"] == "user" and not self._state.goal:
            self._state = replace(self._state, goal=prepared["content"])

    def get_history(self):
        """活动原始对话及有界 observation 的副本；旧段落由 archive 引用保存。"""
        return deepcopy(self._active)

    @property
    def last_compression(self):
        return self._last_compression

    @property
    def last_report(self):
        return deepcopy(self._last_report)

    def _tokens(self, value):
        return count_tokens(self.estimator, [{"role": "user", "content": json_text(value) if not isinstance(value, str) else value}])

    def _current(self, active):
        return next((m["content"] for m in reversed(active) if m["role"] == "user"), "")

    def _working(self, active, summary):
        latest = next((i for i in range(len(active) - 1, -1, -1) if active[i]["role"] == "user"), None)
        return {"summary": summary, "messages": [m for i, m in enumerate(active) if i != latest]}

    def _render(self, active, summary, memories, state):
        return assemble(self._system_prompt, self._schemas, state, memories,
                        self._working(active, summary), self._current(active))

    def _total(self, messages):
        # schemas 同时计入 XML 与模型的原生 tools 参数，避免隐藏的双份开销。
        return count_tokens(self.estimator, messages) + self._native_schema_tokens()

    def _native_schema_tokens(self):
        if not self._schemas:
            return 0
        estimate = getattr(self.estimator, "estimate_tools", None)
        if callable(estimate):
            count = estimate(deepcopy(self._schemas))
            if type(count) is not int or count < 0:
                raise ContextError("工具 Token 计数器必须返回非负整数")
            return count
        return self._tokens(self._schemas) + self.config.tool_schema_overhead_tokens * len(self._schemas)

    def estimate_request_tokens(self, messages):
        return self._total(messages)

    def count_tokens(self):
        if self._cache_key == json_text(self.snapshot_state()):
            return self._total(self._cache)
        return self._total(self._render(self._active, self._summary, self._memories, self._state.to_dict()))

    def _report(self, value):
        self._last_report = deepcopy(value)
        if self._observer is not None:
            try:
                self._observer(deepcopy(value))
            except Exception:
                pass

    def _rolling_summary(self, removed, previous, archive_id):
        config, failures, level = self.config, 0, 1
        source = ([{"role": "assistant", "content": json_text(previous)}] if previous else []) + removed
        source = WindowReducer(self.estimator, config.summary_input_tokens).bounded_history(source, config.summary_input_tokens)
        text = "摘要不可用；旧历史已存档，可按 Result_ID 查询。"
        if self._summarizer is not None:
            try:
                generated = self._summarizer(deepcopy(source), config.summary_tokens)
                if not isinstance(generated, str) or not generated.strip():
                    raise ContextError("摘要器返回无效内容")
                text = generated.strip()
                if self._tokens(text) > config.summary_tokens:
                    level = 2
                    bounded = fit_text(text, config.summary_input_tokens, self.estimator)
                    text = self._summarizer([{"role": "assistant", "content": bounded}], config.summary_tokens)
                    if not isinstance(text, str) or not text.strip():
                        raise ContextError("二级摘要器返回无效内容")
            except Exception:
                text, failures = "摘要失败；旧历史已存档，可按 Result_ID 查询。", 1
        else:
            failures = 1
        summary = {"start_time": (previous or {}).get("start_time") or removed[0].get("context_time", "unknown"),
                   "end_time": removed[-1].get("context_time", "unknown"),
                   "entities": deepcopy(self._state.entities),
                   "unfinished_items": deepcopy(self._state.todo_list), "level": level, "text": text,
                   "archive_result_id": archive_id}
        # 摘要元数据也计入预算。先保留时间范围，再逐项缩短辅助元数据。
        while self._tokens(summary) > config.summary_tokens and summary["entities"]:
            summary["entities"].pop(next(reversed(summary["entities"])))
        while self._tokens(summary) > config.summary_tokens and summary["unfinished_items"]:
            summary["unfinished_items"].pop()
        allowance = config.summary_tokens - self._tokens({**summary, "text": ""})
        summary["text"] = fit_text(text, max(0, allowance), self.estimator)
        if self._tokens(summary) > config.summary_tokens:
            raise ContextBudgetExceededError("摘要预算不能容纳时间范围等必要元数据")
        return summary, failures

    def get_windowed_messages(self):
        self._last_compression = None
        cache_key = json_text(self.snapshot_state())
        if cache_key == self._cache_key and not self._pending_truncated:
            return deepcopy(self._cache)
        active, memories, state, summary = deepcopy(self._active), deepcopy(self._memories), self._state.to_dict(), deepcopy(self._summary)
        exchange_groups(active)
        before = self._total(self._render(active, summary, memories, state))
        actions, removed, failures, truncated = [], [], 0, self._pending_truncated
        cfg = self.config
        if self._tokens(section("system_prompt", self._system_prompt + "\n" + SYSTEM_GUARD + "\n" + FINAL_REMINDER)) > cfg.system_prompt:
            raise ContextBudgetExceededError("system_prompt 超过配置预算")
        if self._tokens(section("tool_schemas", self._schemas)) + self._native_schema_tokens() > cfg.tool_schemas:
            raise ContextBudgetExceededError("tool_schemas 超过配置预算")
        if self._tokens(section("current_user_input", self._current(active))) > cfg.user_input_buffer:
            raise ContextBudgetExceededError("current_user_input 超过配置预算；用户意图不会被静默改写")

        def messages():
            return self._render(active, summary, memories, state)

        def working_over():
            return self._tokens(section("working_memory", self._working(active, summary))) > cfg.working_memory

        def total_over():
            return self._total(messages()) > cfg.input_budget

        # 1. observation 的原始载荷已经外化；继续消除可选预览。
        if working_over() or total_over():
            for index, message in enumerate(active):
                if message["role"] == "tool":
                    compact = self._projector.compact(message)
                    if self._tokens(section("observation", compact)) < self._tokens(section("observation", message)):
                        active[index] = compact
                        truncated += 1
            actions.append("truncate_observation")
        # 2. 完整分组的滑动窗口；最近 N 是上限，预算不足时进一步移出旧分组。
        groups = exchange_groups(active)
        latest_user = next((g for g in reversed(groups) if g[0]["role"] == "user"), None)
        while len(groups) > 1 and (len(groups) > cfg.recent_turns + (1 if latest_user else 0)
                                  or working_over() or total_over() or len(active) > cfg.history_messages
                                  or removed and (self._tokens(section("working_memory", self._working(active, summary))) + cfg.summary_tokens > cfg.working_memory
                                                  or self._total(messages()) + cfg.summary_tokens > cfg.input_budget)):
            eligible = next((i for i, g in enumerate(groups[:-1]) if g is not latest_user), None)
            if eligible is None:
                break
            removed.extend(groups.pop(eligible))
            active = [m for g in groups for m in g]
            # 先选定摘要输入，再调用一次摘要器，避免逐条循环产生模型费用。
        if removed:
            if self._scope is None:
                raise ContextError("归档旧历史必须先绑定宿主范围")
            archive_payload = {"messages": removed,
                               "previous_archive": (summary or {}).get("archive_result_id")}
            archive, _ = self._projector.project({"role": "tool", "call_id": "archive-" + self._projector.digest(json_text(archive_payload)),
                "content": json_text({"output": archive_payload, "is_error": False})}, self._scope, "context_history")
            archive_id = loads(archive["content"])["observation"]["Result_ID"]
            summary, failures = self._rolling_summary(removed, summary, archive_id)
            actions.append("summarize_working_memory" if not failures else "summary_fallback")
        # 3. 逐项减少检索 TopK，不截断一条证据的语义。
        while memories and (self._tokens(section("long_term_memory", memories)) > cfg.long_term_memory or total_over()):
            memories.pop()
            if "reduce_memory_topk" not in actions:
                actions.append("reduce_memory_topk")
        # 4. 优先省略已完成步骤、计划、非关键实体；目标与待办事项保持原样。
        for name in ("completed_steps", "plan", "entities"):
            while state[name] and (self._tokens(section("task_state", state)) > cfg.task_state or total_over()):
                if isinstance(state[name], list):
                    state[name].pop(0)
                else:
                    state[name].pop(next(reversed(state[name])))
                if "compress_task_state" not in actions:
                    actions.append("compress_task_state")
        built, after = messages(), self._total(messages())
        if working_over() or self._tokens(section("task_state", state)) > cfg.task_state or after > cfg.input_budget:
            self._report({"input_tokens": after, "input_budget": cfg.input_budget, "actions": actions,
                          "summary_failures": failures, "status": "budget_exceeded"})
            raise ContextBudgetExceededError("降级后必要任务状态、最近消息或 XML 包装仍超过上下文预算")
        # 所有检查通过再提交，归档先于窗口提交，持久化失败不得丢失历史。
        if removed:
            # 旧段落通过 previous_archive 串联，进程内只保存最新引用。
            self._archives = [archive_id]
        self._active, self._summary, self._memories = active, summary, memories
        self._pending_truncated = 0
        if actions or truncated:
            self._last_compression = CompressionRecord(before, after, len(removed), "layered",
                                                       f"removed={len(removed)}, truncated={truncated}", truncated)
        self._report({"input_tokens": after, "input_budget": cfg.input_budget,
                      "output_reserve": cfg.output_reserve, "actions": actions, "memory_topk": len(memories),
                      "summary_failures": failures, "status": "ready",
                      "layer_tokens": {
                          "system_prompt": self._tokens(section("system_prompt", self._system_prompt + "\n" + SYSTEM_GUARD + "\n" + FINAL_REMINDER)),
                          "tool_schemas": self._tokens(section("tool_schemas", self._schemas)) + self._native_schema_tokens(),
                          "task_state": self._tokens(section("task_state", state)),
                          "long_term_memory": self._tokens(section("long_term_memory", memories)),
                          "working_memory": self._tokens(section("working_memory", self._working(active, summary))),
                          "user_input_buffer": self._tokens(section("current_user_input", self._current(active)))}})
        self._cache_key, self._cache = json_text(self.snapshot_state()), deepcopy(built)
        return deepcopy(built)

    def snapshot_state(self):
        return deepcopy({"kind": "layered", "version": 2, "config": asdict(self.config),
                         "system_prompt": self._system_prompt, "scope": asdict(self._scope) if self._scope else None,
                         "task_state": self._state.to_dict(), "active": self._active, "summary": self._summary,
                         "memories": self._memories, "archives": self._archives, "tool_schemas": self._schemas,
                         "recent_memory_ids": self._recent_memory_ids,
                         "pending_truncated": self._pending_truncated})

    def restore_state(self, data):
        if isinstance(data, dict) and data.get("version") == 1:
            # 旧快照没有跨 Run 已完成历史；仅补充空来源集合，不重建历史。
            data = {**data, "version": 2, "recent_memory_ids": []}
        expected = set(self.snapshot_state())
        if not isinstance(data, dict) or set(data) != expected or data["kind"] != "layered" or data["version"] != 2 or data["config"] != asdict(self.config) or data["system_prompt"] != self._system_prompt:
            raise ContextError("分层上下文快照配置不匹配；存储、摘要器与计数器需重新注入")
        try:
            scope = MemoryScope(**data["scope"]) if data["scope"] else None
            state = TaskState.parse(data["task_state"])
            active = [validate_message(m) for m in data["active"]]
            memories = self._validate_memories(data["memories"])
            recent_ids = data["recent_memory_ids"]
            if not isinstance(recent_ids, list) or any(not isinstance(v, str) or not v for v in recent_ids) or len(set(recent_ids)) != len(recent_ids):
                raise ContextError("快照已完成历史的来源标识无效")
            if scope is not None and state.task_id != scope.task_id:
                raise ContextError("快照任务状态与宿主范围不符")
            if type(data["pending_truncated"]) is not int or data["pending_truncated"] < 0:
                raise ContextError("快照 observation 计数无效")
            if not isinstance(data["archives"], list) or len(data["archives"]) > 1 or any(not isinstance(r, str) for r in data["archives"]):
                raise ContextError("快照历史引用无效")
            summary = data["summary"]
            if summary is not None:
                required = {"start_time", "end_time", "entities", "unfinished_items", "level", "text", "archive_result_id"}
                if not isinstance(summary, dict) or set(summary) != required or any(not isinstance(summary[k], str) for k in ("start_time", "end_time", "text", "archive_result_id")) or type(summary["level"]) is not int or summary["level"] not in {1, 2}:
                    raise ContextError("快照滚动摘要格式无效")
                if not isinstance(summary["entities"], dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in summary["entities"].items()) or not isinstance(summary["unfinished_items"], list) or any(not isinstance(v, str) for v in summary["unfinished_items"]):
                    raise ContextError("快照滚动摘要实体或待办无效")
                archive = self._projector.store.get(summary["archive_result_id"], scope)
                if data["archives"] != [summary["archive_result_id"]] or archive is None or archive.tool_name != "context_history":
                    raise ContextError("快照滚动摘要归档引用无效")
            if not isinstance(data["tool_schemas"], list) or any(not isinstance(d, dict) or not isinstance(d.get("name"), str) for d in data["tool_schemas"]):
                raise ContextError("快照工具定义格式无效")
            if self._scope is not None and self._scope != scope:
                raise ContextError("分层快照的记忆范围不匹配")
            for message in active:
                if message["role"] == "system":
                    raise ContextError("快照不能注入系统消息")
                if message["role"] == "tool":
                    value = loads(message["content"])
                    reference = value["observation"]
                    record = self._projector.store.get(reference["Result_ID"], scope)
                    if record is None or record.digest != reference["digest"]:
                        raise ContextError("快照 observation 引用不存在或校验不符")
                    projected, _ = self._projector.project({"role": "tool", "call_id": message["call_id"],
                                                            "content": record.payload_json}, scope,
                                                           record.tool_name, persist=False)
                    if message["content"] not in {projected["content"], self._projector.compact(projected)["content"]}:
                        raise ContextError("快照 observation 内容与持久记录不符")
            json_text(data)
        except (TypeError, ValueError, KeyError) as error:
            raise ContextError("分层上下文快照无效") from error
        self._scope, self._state, self._active, self._memories = scope, state, active, memories
        self._recent_memory_ids = list(recent_ids)
        self._summary, self._archives, self._schemas = deepcopy(data["summary"]), deepcopy(data["archives"]), deepcopy(data["tool_schemas"])
        self._last_compression, self._pending_truncated = None, data["pending_truncated"]
        self._cache_key, self._cache = None, None

    def validate_pending_exchange(self, response, index, results=None):
        tail = self._active[-(index + 1):]
        assistant = {"role": "assistant", "content": response["text"]}
        if response["tool_calls"]:
            assistant["tool_calls"] = response["tool_calls"]
        normalized = [{k: v for k, v in m.items() if k not in {"context_time", "source_digest"}} for m in tail]
        if len(normalized) != index + 1 or normalized[0] != assistant:
            raise ContextError("快照游标与助手工具调用不匹配")
        if results is not None and len(results) != index:
            raise ContextError("快照工具结果数与游标不匹配")
        for offset, (message, call) in enumerate(zip(normalized[1:], response["tool_calls"][:index])):
            if message.get("role") != "tool" or message.get("call_id") != call["call_id"]:
                raise ContextError("快照游标与工具结果不匹配")
            if results is not None:
                try:
                    digest = loads(message["content"])["observation"]["digest"]
                except (ValueError, KeyError, TypeError):
                    raise ContextError("快照 observation 校验信息无效") from None
                if tail[offset + 1].get("source_digest", digest) != self._projector.digest(results[offset]):
                    raise ContextError("快照上下文与已保存工具结果不匹配")
