"""共享窗口缩减器；失败不会污染调用方的历史。"""

from copy import deepcopy
from json import dumps, loads

from .contracts import ContextBudgetExceededError, ContextError
from .records import CompressionRecord, WindowBuild
from .validation import count_tokens, exchange_groups


def tool_preview(content, length):
    try:
        decoded = loads(content)
    except (TypeError, ValueError):
        decoded = {}
    return dumps({"output": {"context_truncated": True,
                            "original_characters": len(content),
                            "preview": content[:length]},
                  "is_error": isinstance(decoded, dict) and decoded.get("is_error") is True},
                 ensure_ascii=False)


def fit_text(text, limit, estimator, *, suffix=" [摘要已截断]"):
    def measure(value):
        return count_tokens(estimator, [{"role": "assistant", "content": value}])
    if measure(text) <= limit:
        return text
    if measure(suffix) > limit:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle] + suffix) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low] + suffix


class WindowReducer:
    def __init__(self, estimator, token_budget, *, soft=False):
        self.estimator, self.budget, self.soft = estimator, token_budget, soft

    def reduce(self, messages, *, summarizer=None, summary_tokens=0, summary_input_tokens=0):
        original = deepcopy(messages)
        before = count_tokens(self.estimator, original)
        groups = exchange_groups(original, strict=not self.soft)
        latest_user = next((i for i in range(len(groups) - 1, -1, -1)
                            if groups[i][0]["role"] == "user"), None)
        protected = {len(groups) - 1}
        if not self.soft and latest_user is not None:
            protected.add(latest_user)
        protected.update(i for i, g in enumerate(groups) if g[0]["role"] == "system")
        active = list(range(len(groups)))
        removed, truncated = [], 0

        def flatten():
            return [m for i in active for m in groups[i]]

        # 软预算只供旧 build 调用；不缩短最新消息，也不承担模型请求预算。
        if not self.soft and before > self.budget and not summarizer:
            tools = sorted((m for m in flatten() if m["role"] == "tool"),
                           key=lambda m: len(m["content"]), reverse=True)
            # 先移出可替换旧分组，避免为了旧历史破坏上一步 observation。
            for index in list(active):
                if count_tokens(self.estimator, flatten()) <= self.budget:
                    break
                if index not in protected:
                    active.remove(index)
                    removed.extend(groups[index])
            for message in tools:
                if message not in flatten() or count_tokens(self.estimator, flatten()) <= self.budget:
                    continue
                content = message["content"]
                message["content"] = tool_preview(content, 0)
                if count_tokens(self.estimator, [message]) >= count_tokens(self.estimator, [{**message, "content": content}]):
                    message["content"] = content
                    continue
                low, high = 0, len(content)
                if count_tokens(self.estimator, flatten()) <= self.budget:
                    while low < high:
                        middle = (low + high + 1) // 2
                        message["content"] = tool_preview(content, middle)
                        if count_tokens(self.estimator, flatten()) <= self.budget:
                            low = middle
                        else:
                            high = middle - 1
                message["content"] = tool_preview(content, low)
                truncated += 1

        reserve = min(summary_tokens, self.budget // 4) if summarizer and before > self.budget else 0
        for index in list(active):
            if count_tokens(self.estimator, flatten()) <= self.budget - reserve:
                break
            if index not in protected:
                active.remove(index)
                removed.extend(groups[index])
        kept, strategy = flatten(), "trim_oldest"
        if removed and reserve:
            try:
                summary_input = self.bounded_history(removed, summary_input_tokens)
                summary = summarizer(deepcopy(summary_input), reserve)
                if isinstance(summary, str) and summary.strip():
                    available = min(reserve, self.budget - count_tokens(self.estimator, kept))
                    summary = fit_text(summary.strip(), available, self.estimator)
                    item = {"role": "assistant", "content": summary, "context_summary": True}
                    at = next((i for i, m in enumerate(kept) if m["role"] != "system"), len(kept))
                    proposed = kept[:at] + [item] + kept[at:]
                    if summary and count_tokens(self.estimator, proposed) <= self.budget:
                        kept, strategy = proposed, "summarize"
            except Exception:
                pass
        after = count_tokens(self.estimator, kept)
        if after > self.budget and not self.soft:
            # 摘要也可能因受保护 observation 超限；使用共享硬预算缩减器回退。
            if summarizer:
                return WindowReducer(self.estimator, self.budget).reduce(messages)
            raise ContextBudgetExceededError("系统提示、最新用户消息或工具调用结构超过上下文预算")
        record = None
        if removed or truncated:
            record = CompressionRecord(before, after, len(removed), strategy,
                                       f"removed={len(removed)}, truncated={truncated}", truncated)
        return WindowBuild(deepcopy(kept), record)

    def bounded_history(self, history, budget):
        selected = []
        for group in reversed(exchange_groups(history)):
            candidate = deepcopy(group) + selected
            if count_tokens(self.estimator, candidate) <= budget:
                selected = candidate
        if not selected and history:
            text = fit_text(dumps(history, ensure_ascii=False), budget, self.estimator)
            if text:
                selected = [{"role": "assistant", "content": text, "context_summary": True}]
        return selected


class MessageLedger:
    def __init__(self, token_budget, estimator, strategy, system_prompt):
        self.token_budget, self.estimator, self.strategy = token_budget, estimator, strategy
        self.system_prompt = system_prompt
        self.history, self.active = [], []
        self.last_compression = None

    def systems(self):
        return [] if self.system_prompt is None else [{"role": "system", "content": self.system_prompt}]

    def append(self, message):
        self.history.append(deepcopy(message))
        self.active.append(deepcopy(message))

    def window(self):
        from .validation import validate_message

        original = self.systems() + deepcopy(self.active)
        count_tokens(self.estimator, original)
        build = self.strategy.compress(deepcopy(original), token_budget=self.token_budget, estimator=self.estimator)
        if not isinstance(build, WindowBuild):
            raise ContextError("压缩策略必须返回 WindowBuild")
        messages = [validate_message(m) for m in build.messages]
        if count_tokens(self.estimator, messages) > self.token_budget:
            raise ContextBudgetExceededError("压缩策略返回的窗口仍超过上下文预算")
        if [m for m in messages if m["role"] == "system"] != [m for m in original if m["role"] == "system"]:
            raise ContextError("压缩策略不能修改或移除系统提示")
        latest_user = next((m for m in reversed(original) if m["role"] == "user"), None)
        if latest_user is not None and latest_user not in messages:
            raise ContextError("压缩策略不能修改或移除最新用户消息")
        exchange_groups(messages)
        groups = exchange_groups(original)
        for item in groups[-1] if groups else []:
            if item["role"] != "tool" and item not in messages:
                raise ContextError("压缩策略不能移除最新消息或工具调用")
            if item["role"] == "tool" and not any({k: v for k, v in m.items() if k != "content"} == {k: v for k, v in item.items() if k != "content"} for m in messages):
                raise ContextError("压缩策略不能移除最新工具结果的调用结构")
        if self.system_prompt is not None:
            if messages[:1] != self.systems():
                raise ContextError("系统提示必须保持在窗口开头")
            messages = messages[1:]
        self.active, self.last_compression = deepcopy(messages), build.compression
        return self.systems() + deepcopy(messages)
