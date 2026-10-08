# ADR 0012：分层 Context、外化结果与受控记忆工具

- 状态：已采纳
- 日期：2026-10-05
- 约束：[架构](../architecture.md)、[开发指南](../Slothy-Development-Guide.md)
- 关联：ADR 0008、0010、0011

## 问题

旧 Context 只有消息列表与窗口压缩，不能预算原生工具定义、回复空间与 Prompt 包装。长工具结果同时留在历史和 Runtime 工具日志中。检索、任务状态、上下文信任边界和摘要服务故障需要独立管理，不能继续扩展 Runner 的辅助逻辑。

## 决定

1. 删除 memory/window/strategies 的旧实现，保留同路径、同类名和方法签名的兼容适配器，委托共享 MessageLedger/WindowReducer。CompressionRecord/WindowBuild 移入 records 并在原模块重导出。旧调用、同步语义、异常类和旧快照格式继续支持。ContextWindow.build 保留历史软预算语义；get_windowed_messages 拒绝将软预算超限结果发送给模型。
2. 新产品组装注入 LayeredContext，继续实现 add/get_windowed_messages/last_compression。System Prompt、Working Memory、Task State、Long-Term Memory 分层。TaskState 只能通过宿主结构化接口更新；摘要与检索不得隐式更改完成状态。
3. Prompt 由可信 system 消息和不可信 user 数据消息组成。XML 标签按约定顺序排列，数据一律转义。完整工具请求/结果对作为 working_memory 内的 JSON 数据保留，不构造伪造的原生 tool 消息；后续工具调用继续通过模型原生 tools 参数提出。
4. W 来自配置的生成模型能力，O 明确预留并传为 max_tokens；安全余量另行扣除。最终请求计数包括 XML、消息封装和原生工具定义。各层预算、滑动窗口、摘要和 observation 限额集中配置。超限按 observation → working summary → memory TopK → task state 顺序降级；不可省略的系统规则、用户意图和待办超限时报 ContextBudgetExceededError。Qwen chat 关闭思考以避免 max_tokens 只限制可见回答；其他模型的输出语义由部署者核对。
5. Core 只定义 ObservationStore、MemoryRepository、EmbeddingProvider、RetrievalChannel 和 Reranker。SQLite/FTS5、HTTP、SDK、环境读取、线程隔离与配置组装全部放 Infrastructure。Application 提供独立 MemoryAPI/MemoryService，不导入 Infrastructure 或 main。
6. 工具结果先在受控执行器外化，后提交 ToolJournal。Context 再验证引用并构建有界投影。SQLite 使用 owner/session/task 范围和 SHA-256 原文完整性校验；不能查到的引用失败关闭，不能据此重新执行已完成的副作用工具。工具结果为空或错误也有结构化 observation。
7. RAG 通过 search_memory 工具挂载，get_result 提供受限分页。参数验证、策略、宿主范围与执行分离；定义标为 IDEMPOTENT。模型不能提供 owner_id 或数据库路径，不能读取别人的结果。装饰器保留原执行器的幂等核验能力，UNVERIFIABLE/UNKNOWN 仍沿用 ADR 0010 的审批阻塞。
8. 检索通道分别设置超时和权重，融合候选去重、实体过滤与时间衰减；重排失败回退融合排序。FTS5 不可用时退回有界 Python BM25；SQLite 向量余弦是可替换的基线通道，部署大索引需要注入索引服务。
9. 摘要仅调用 DASHSCOPE_CHAT_MODEL，DASHSCOPE_MODEL 只调用 embedding API，重排采用独立 DASHSCOPE_RERANK_MODEL。摘要输入包装、输出及二级摘要再次预算。失败保留结构化降级说明、时间范围、实体、未完成事项与历史归档 Result_ID；历史链存储在外部，进程内保留最新引用。
10. ContextCompressed 与数值 Metric 沿用原事件契约；检索/分层报告只含计数、分类和固定阶段名。观察者异常隔离。密钥不进入 Core、DTO、快照或日志；具体适配器只读环境，旧 api_key 参数保留但不作为认证源。

## 后果与边界

- 兼容模式保留旧消息布局与原始历史，不包含生产分层能力；这是显式迁移适配，不是新的产品默认配置。新宿主应使用 ContextComponents 创建分层 Context 与受控执行器，并注入 RuntimeService。
- 分层快照是新 kind/version；旧在途 Run 使用旧适配器恢复至结束，新 Run 切换分层工厂。不要直接改写在途工具日志或丢掉审批/回执。
- Context 数据和 Runtime 快照是两个 SQLite 事务域。工具结果必须先保存外化记录；失败后可能有孤立记录，不能以删除它们换取自动重放副作用。备份与恢复须同时保留两者。
- 超时线程不能强制杀死任意 Python/SDK 调用。隔离容量有上限，晚到结果被忽略；服务适配器同时设置 I/O 超时。挂起线程耗尽容量时立即降级，未授权工具不会因此被重新执行。
- 默认 token 计数是启发式；精确部署必须注入模型 tokenizer，并配置真实生成模型 W。SQLite 不加密、没有持久认证目录；宿主负责认证、文件权限、生命周期与保留策略。
- XML 转义阻止结构逃逸，但不能保证模型抵御所有语义注入。安全边界仍是受控工具、参数验证、宿主权限和 Policy。

## 验证

旧 Core 回归、假模型/假 HTTP 的模型隔离、8k 长任务、RAG 权限与回退、SQLite 完整性、分页连续性、摘要二级压缩与失败、工具快照无长原文以及暂停恢复均由自动测试覆盖。不使用真实模型 API 作为单元或集成测试前置条件。
