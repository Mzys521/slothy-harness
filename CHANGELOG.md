# 更新日志

本文件记录 Slothy 各版本的主要变化。

## 0.2.0 — 2026-10-05

### Application 接口、演示组装与后续计划

- 新增 RuntimeAPI、RuntimeService 与请求/状态/审批/工具/事件 DTO，按既有 Application API → Service → Core 分层注入依赖。创建、执行、控制、审批和恢复分别处理单一用例，返回可序列化成功或受控错误响应；包含运行归属检查、版本绑定和单驱动保护。
- Application 接收 Core 事件并推送 DTO 副本，提供有限缓存分页和监听失败计数；审批参数经单独接口展示，状态/事件不暴露原始快照。可信宿主可登记已保存 Run，尚未消费的批准不跨 Service 重建继承。
- Core 增加当前 Run 的只读入口、驱动线程检查点取消意图及已保存快照的受控取消；保持原直接取消/运行调用兼容。main 默认无网络组装 Context、组合 Policy、Observation、快照及 Application；真实调用使用 --live，交互输入使用 --live --interactive。
- 修复演示工具打印丢失普通 EventSink、共享 EventBus 累积自动打印订阅的问题。新增 Application 原子用例和实际计算执行器/SQLite 组装验证。
- 新增接口说明、演示说明、ADR 0011 和 MCP/RAG 后续计划；MCP/RAG 本轮只规划，不新增实现或依赖。产品桌面桥接、认证/归属持久目录和后台调度仍待后续接入。

### Runtime 快照、恢复与工具重放

- 新增版本化 JSON `RuntimeSnapshot`、`SnapshotStore`、内存与 SQLite 存储，保存 Run/Step、Context、模型/策略计数、工具日志和批次游标。`AgentRunner.resume()` 通过 `RunExecution` 恢复，已完成结果及批次前缀不重复执行，恢复不重置已记录预算。
- 新增 `Run.interrupt()`、`SUSPENDED`、`WAITING_APPROVAL` 和恢复代数。取消为不可恢复终止；暂停后的取消也持久化。存储以事务比较版本，旧快照和旧审批被拒绝。
- 工具新增 `ReplaySafety` 和实现版本：普通幂等工具支持重试，非幂等工具用稳定键与参数指纹查询凭据，不可校验的尝试在执行前等待用户决定。一次同意仅允许一次尝试，授权不序列化；拒绝向模型返回受控错误。原策略 `ASK` 的拦截语义保持兼容。
- 新增 SQLite 幂等凭据适配器、四个恢复/审批事件和无网络演示，覆盖副作用与结果提交之间的崩溃窗口。说明见 `docs/runtime-recovery.md`、ADR 0010；桌面审批 UI、进程硬中断及任意外部副作用的 exactly-once 不在本轮范围内。

### 策略与韧性

- 新增 `Policy`、`DefaultPolicy`、`TimeoutPolicy`、`RetryPolicy`、`SafetyPolicy` 与每次运行独立的 `PolicySession`。Runner 通过策略决定终止，兼容原 `max_steps`、`PolicyEngine` 和 Run 时限；更换策略不改 Runner。
- 支持协作式总/步骤/调用时限、有界临时故障重试、显式幂等工具重试列表、工具异常安全反馈和连续重复往返检测。剩余时限传给模型和工具；重试不重置预算，流式文本已交付时不重放。
- MiMo 禁用 SDK 自动重试，映射临时服务故障和超时，关闭结束或失败的流。新增无网络策略演示及测试。说明见 `docs/policy-system.md`，设计记录见 ADR 0009；进程级硬中断尚未实现。

### 正式 Context System

- 新增 `Context`、`CompressionStrategy` 与 `InMemoryContext`，分开管理完整原始历史和发送窗口，返回副本；Runner 改经 `get_windowed_messages()` 读取，最终模型回答写入历史。默认消息预算为 8192，可注入计数器与策略，旧 `ContextWindow` 保持兼容。
- 实现整组工具往返截断和超长工具结果的合法 JSON 预览；实现可注入摘要器的 `SummaryStrategy`，限制摘要输入/输出，故障时回退截断。补齐平铺工具调用参数计数；新增上下文错误分类和兼容的 `ContextCompressed.messages_truncated`。
- 新增无网络长任务演示和单元/集成测试，验证超过 90k 的原始历史在每次请求中保持 8k 估算预算。使用说明见 `docs/context-system.md`，设计记录见 ADR 0008。

### Runner 模块入口拆分

- 清除 `runner.py` 中的领域辅助函数，将上下文追加与消息转换、模型调用/流式/用量、工具执行/进度/错误、策略事件分别移回所属 Core 模块。runner 通过固定的 `add`、`model_call`、`tool_call` 入口编排 Run/Step，保持已有调用方式与事件顺序。
- 各模块共用 `EventEmitter` 与 Run 中继，耗时指标归 `runtime/observation.py`；上下文初始化失败会正确结束 Run，已结束工具的旧进度回调在复用调用 ID 时仍失效。新增模块入口与重复运行隔离回归测试，设计记录见 `docs/decisions/0007-runner-module-entrypoints.md`。

### 运行时事件

- 新增 `core/events`：Run/Step 生命周期、模型调用、工具调用、状态与策略、观测五类运行时事件契约，以及按事件类型分发的 `EventBus` 和按顺序记录事件的 `RunTimeline`。
- Runtime 在既有状态迁移处发出事件，`AgentRunner` 在模型和工具调用边界发出事件并汇总令牌用量与耗时指标；`AgentRunner.run` 新增可选参数 `events`，`Run` 新增可选字段 `events` 与 `step_timeout_seconds`。
- 新增步骤级时限；取消、总时限和步骤时限统一在调用边界检查并发出对应事件。`core/runtime` 新增 `RunStateError`、`StepTimeoutError`、`StepLimitExceededError`。
- 事件只携带标识、计数、状态、耗时和错误分类；观察者的异常由事件总线隔离并记录，不影响运行结果。提供方和执行器可通过 `LLMTimeoutError`、`ToolTimeoutError` 让事件给出准确的错误分类。
- 新增核心单元测试覆盖事件契约、分发、失败隔离及直接回答、工具往返、工具错误、步数上限、取消和超时的完整事件顺序。设计记录见 `docs/decisions/0003-runtime-event-contract.md`，使用说明见 `docs/runtime-events.md`。

### 上下文、策略、进度与流式

- 新增 `core/context`：`MessageRole`、`TokenEstimator` 与 `HeuristicTokenEstimator`、以及按令牌预算裁剪最早消息的 `ContextWindow`；运行器在每次模型请求前准备上下文，裁剪发生时发出 `ContextCompressed`。保留系统提示与“助手调用 + 工具结果”配对，至少保留最新一条消息。设计记录见 `docs/decisions/0004-context-window-and-trim-strategy.md`。
- 新增 `core/policy`：`PolicyDecision`、`PolicyEngine` 与 `ToolNameRule`、`AllowlistRule`；运行器在工具调用边界判定 `ALLOW`/`DENY`/`ASK`，被拦截的调用不进入执行器，改为向模型返回受控错误结果，并发出 `PolicyTriggered` 与 `GuardrailBlocked`。`ASK` 当前与 `DENY` 一样被拦截，审批流程尚未实现。设计记录见 `docs/decisions/0005-policy-decision-and-guardrail.md`。
- `ToolExecutor.execute` 新增可选进度回调参数，`core/tools` 新增 `ProgressReport` 与 `ProgressCallback`；执行器上报的进度转换为 `ToolProgress` 事件，调用结束后回调失效。设计记录见 `docs/decisions/0006-tool-progress-and-streaming.md`。
- MiMo 适配器支持流式响应：运行器传入 `on_chunk` 时改用流式请求，逐段回调文本增量（转换为 `TokenChunk`），并按 `index` 拼装工具调用分片；未传入时保持一次性请求。
- 新增 `scripts/demo_governance.py`，用假模型和假执行器演示一次运行中的压缩、进度、策略拦截与流式分片事件顺序。

### 命令行工具回调

- `main.py` 新增 `ToolReporter`：订阅 `ToolCallStart`、`ToolCallEnd`、`GuardrailBlocked` 事件，打印 `[tool running] <工具名>`、`[tool run success] <工具名>`、`[tool run failed] <工具名>` 与 `[tool blocked] <工具名>`。回调只读取工具名与 `is_error`，不打印参数或结果内容；被拦截的调用不会重复打印失败行。
- `run_calculation` 新增 `watch_tools` 参数（默认 `True`），传 `False` 可静默运行；已有集成测试关闭该回调，保持测试输出干净。

## 0.1.0 — 2026-10-04

首个开发版本。

- 实现核心智能体循环及 Run/Step 状态、取消和截止时间控制，并将运行器及结果类型归入 `core/runtime`。
- 实现模型提供方抽象、工具定义和注册表、抽象工具执行器；工具上下文及结果类型归入 `core/tools`。
- 提供 MiMo 模型适配器，以及位于 `infrastructure/app_tools` 的加、减、乘、除、幂计算工具和具体执行器。
- 提供命令行计算示例、Vue 前端工作区，以及核心单元测试和集成测试。

桌面宿主与前端桥接层尚未接入。
