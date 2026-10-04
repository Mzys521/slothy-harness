# Context System

正式上下文系统把完整历史和实际发送给模型的窗口分开。Runner 通过固定的 `get_windowed_messages()` 入口读取请求上下文；计数、截断和摘要都在 `core/context` 内完成，切换策略无需修改循环。设计见 [ADR 0008](decisions/0008-context-system.md)。

| 文件 | 职责 |
| --- | --- |
| `core/context/contracts.py` | `Context`、`CompressionStrategy`、摘要器类型与受控错误 |
| `core/context/memory.py` | 原始历史、活动窗口、输入校验及压缩后复核 |
| `core/context/estimator.py` | 可替换计数器；默认字符启发式，计入工具参数及调用标识 |
| `core/context/strategies.py` | 完整单位裁剪、工具结果缩短、摘要和故障回退 |
| `core/context/conversation.py` | `add` 消息转换与压缩事件转发 |

## 默认截断

```python
from slothy.core.context import InMemoryContext
from slothy.core.runtime import AgentRunner

context = InMemoryContext(token_budget=8192, system_prompt="完成当前任务。")
runner = AgentRunner(model, registry, executor, context=context, max_steps=32)
result = runner.run(user_input, context=tool_context)

history = context.get_history()             # 原始历史副本，包括最终回答
messages = context.get_windowed_messages()  # 当前预算内窗口副本
tokens = context.count_tokens()             # 当前活动规模，不触发摘要
```

不传 `AgentRunner(context=...)` 时，每次 Run 也默认创建一个 8192 预算的 `InMemoryContext`；仍可通过 `token_budget` 覆盖预算。

裁剪保留系统提示和最新用户意图。助手发起多个工具调用时，全部调用和结果整体保留或整体移除。单个工具结果太大时，在请求窗口中改为带截断标记的 JSON 预览，原始结果留在历史中，工具错误标记保持不变。

如果受保护的系统提示、用户输入或工具调用结构自身已经超限，抛出 `ContextBudgetExceededError`，不发送明知超限的请求。

## 注入摘要器

```python
from slothy.core.context import InMemoryContext, SummaryStrategy

def summarize(messages, output_token_budget):
    # 调用方实现具体摘要：可接模型提供方、离线服务或本地摘要器。
    return summary_service.summarize(messages, max_tokens=output_token_budget)

context = InMemoryContext(
    token_budget=8192,
    system_prompt="完成当前任务。",
    strategy=SummaryStrategy(
        summarize,
        max_summary_tokens=1024,
        max_input_tokens=6144,
    ),
)
runner = AgentRunner(model, registry, executor, context=context)
```

`summarize` 接收历史消息副本和摘要输出预算，返回非空字符串。系统会对摘要输入、输出及最终窗口再次检查预算；输出过长时添加显式截断标记。被替换的历史写成普通助手摘要消息，不能变成系统提示。

摘要器抛出异常、返回空值或摘要空间不足时自动回退到截断。无压缩需要时不调用摘要器。适配器负责它自己的提示、调用用量、模型输出预留和外部调用时限；它的用量不自动计入主模型的 `TokenUsage`。

## 计数与历史边界

默认 `HeuristicTokenEstimator` 仍是启发式估算，不等同提供方 tokenizer，也不用于计费。8192 是注入计数器度量下的请求消息上限。真实部署需为工具定义、请求封装及回复预留空间；可以注入实现 `estimate(messages) -> int` 的精确计数适配器，无需改 Runner。

`get_history()` 保留所有原始内容，包括被移除或缩短的工具结果。历史目前存放在内存中，不包含磁盘持久化。写入与查询采用副本，修改窗口不能改变历史。默认实例只属于本次 Run；显式共享实例时由调用方管理会话范围，不能并发写入同一实例。

旧 `ContextWindow` 仍可使用，其公开列表和软预算语义保持兼容；新开发应使用 `InMemoryContext`。自定义 Context 只需实现 `add`、`get_windowed_messages` 和 `last_compression`，不必提供 `messages` 属性。

## 观测与验收

`ContextCompressed` 记录压缩前后规模、移除数量、工具结果缩短数量与策略名。正式 Context 的预览只包含计数，历史、工具结果与摘要文本不会进入压缩事件。下一次读取未发生新压缩时不重复发出事件。

运行演示：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/demo_context_system.py
```

演示对截断和摘要分别执行 17 步无网络长任务，使用相同的 Runner。完整历史约 90,604 个估算 token，每轮请求最高 8192；摘要策略实际调用注入的假摘要器。对应集成测试还覆盖摘要故障回退、取消和预算无法满足。
