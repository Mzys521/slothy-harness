# 0008 正式 Context System：历史、窗口与压缩策略分离

## 背景

ADR 0004 的 `ContextWindow` 已能裁剪部分旧消息，但仍是公开的消息列表，采用软预算：最新工具结果过长时仍可能把超限请求发送给模型。工具调用参数的计数只识别嵌套提供方格式，遗漏了 Core 的平铺格式。ADR 0007 将消息转换移出 runner，但请求仍经 `Conversation.messages` 属性读取。

本阶段目标是建立独立的 Context 接口，让长任务超过 8k 时自动压缩，切换截断或摘要策略时不修改 Runner。

## 决策

`core/context/contracts.py` 定义结构化 `Context` 协议：

```python
class Context(Protocol):
    def add(self, message: dict[str, Any]) -> None: ...
    def get_windowed_messages(self) -> list[dict[str, Any]]: ...
    @property
    def last_compression(self) -> CompressionRecord | None: ...
```

默认实现 `InMemoryContext` 保留原始历史与活动窗口两个独立集合。写入、历史查询和窗口返回均复制数据。完整历史可通过 `get_history()` 查询；`count_tokens()` 查询当前活动规模，不触发压缩。最终模型回答也写入历史。

默认消息预算为 8192，由可注入的 `TokenEstimator` 度量。默认计数器仍采用字符启发式，并补齐 Core 平铺工具调用、嵌套提供方工具调用、JSON 参数和调用标识的计数。这个预算是计数器度量下的硬上限，不代表提供方真实分词或计费用量。具体 tokenizer 适配器放在 Infrastructure。

`CompressionStrategy.compress(...) -> WindowBuild` 是窗口策略入口。正式 Context 在策略执行后复核预算、系统提示、最新用户消息和工具配对，成功后才更新活动窗口。策略无法改写原始历史。

### 截断策略

`TrimOldestStrategy` 将助手工具调用与全部结果作为不可拆分的单位，从最早的可移除单位开始裁剪。系统提示、最新用户意图和最新消息/工具往返保持保留。

若最新工具结果仍使窗口超限，只缩短工具结果内容：保留角色、调用标识及错误标记，输出合法 JSON，带 `context_truncated`、原始字符数及预算允许的预览。不会改写工具调用参数，也不会重新执行工具。

系统提示、最新用户输入或不可裁剪的调用结构本身超限时，抛出 `ContextBudgetExceededError`，在模型请求前使 Run 失败。不得通过发送已知超限请求来绕过预算。

### 摘要策略

`SummaryStrategy(summarizer, max_summary_tokens=1024, max_input_tokens=8192)` 接收外层注入的同步摘要器：`summarizer(messages, output_token_budget) -> str`。

- 未超预算时不调用摘要器。
- 为摘要预留不超过窗口四分之一的空间，将被替换的旧历史交给摘要器；摘要输入也先限制到独立预算内。
- 摘要放在普通助手消息中，保持系统提示与当前用户意图的优先级。输入或输出发生裁剪时显式标记摘要不完整。
- 摘要器异常、空输出、类型错误或摘要空间不足时回退到截断。额外模型调用、准确计数、提示构造、费用和超时由注入适配器负责，Core 不引用具体 SDK。
- 原始历史始终保留；后续压缩可将旧摘要继续纳入摘要输入，不重复恢复已移出活动窗口的原始消息。

### Runner 与事件

Runner 通过 `context.conversation.add` 写入领域响应，只调用 `get_windowed_messages()` 取得下一次请求，不读取或组装消息列表。`Conversation` 只负责领域消息转换和压缩事件转发，依赖 Context 协议。

模型入口在真正请求之前再次检查 Run 的取消与时限，防止同步摘要期间收到取消后继续调用主模型。

`ContextCompressed` 增加兼容的 `messages_truncated` 字段；新 Context 的压缩预览只含计数，不含原始历史、摘要或工具结果。既有事件分类与统一序列号不变。上下文错误以 `context_error` 或 `context_budget_exceeded` 分类进入 `RunFailed`。

## 理由

历史查询不应依赖当前模型预算，也不应因压缩而丢失真实工具结果。独立窗口策略允许修改裁剪或摘要实现，而保持 Runner 和具体模型适配器的调用方式稳定。通过完整单位保留和硬预算复核，同时约束请求合法性和大小。

## 备选方案

继续只保留公开列表和软预算无法处理超长工具结果。只保存摘要会丢失可检查的原始历史。让 Runner 决定什么时候调用摘要器会重新耦合循环与上下文策略。本次选择接口、历史隔离与实际可用的两种策略。

## 兼容性与限制

- `AgentRunner`、`run_calculation` 的 `context` 参数扩展为 Context 协议，现有构造与运行参数保持兼容。
- `ContextWindow.build()`、公开 `messages` 和旧软预算语义保留；通过新增 `get_windowed_messages()` 可继续注入。正式默认路径使用 `InMemoryContext`。`Conversation.messages` 保留为兼容别名。
- 默认消息预算从 4096 提升为 8192；精确模型窗口还需为工具定义、请求封装和模型输出预留空间，调用方可以配置更小预算并注入对应 tokenizer。
- 历史只在内存中保留，不包含持久化、检查点、记忆注入或并发写入保证。每次 Run 默认创建新实例；共享实例须由调用方明确管理。
- 摘要失真不能由 Core 自动消除；摘要失败回退、完整历史保留和普通消息角色限制其影响。摘要调用的用量不自动并入主模型 `TokenUsage`。

## 验证

无网络长任务使用同一 Runner 跑 16 次工具往返后完成：原始历史约 90,604 个估算 token，每次模型请求最大 8192。分别注入截断、摘要和故障摘要器，核对完成状态、工具结果配对、压缩事件和每次请求预算。另覆盖历史/窗口副本隔离、超长工具结果、摘要输入/输出预算、取消、不可满足预算和独立 Context 实现。
