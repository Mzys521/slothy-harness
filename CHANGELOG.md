# 更新日志

本文件记录 Slothy 各版本的主要变化。

## 0.3.0 — 2026-10-08

### 多提供商与前端模型切换（2026-10-06）

- 设置页接入 DeepSeek、Qwen、MiMo、GLM，预置官方地址与模型，填写 API Key 即可使用。支持 Qwen 区域隔离、模型 ID 添加、模型目录刷新及独立短请求连接测试；输入区提供模型菜单。
- Windows 凭据使用 DPAPI 密文独立落盘；前端/SQLite 配置、任务、快照、事件与记忆不保存密钥。其他平台明确使用进程内凭据，不写入明文。
- Chat/Coding 新任务固定提供商、区域和模型，切换与重启不改变已有运行的绑定。统一 SDK 流式、工具往返、安全错误映射及既有 Runtime 重试；原有 CLI/环境兼容入口保留。见 ADR 0018。


### 独立模式与项目源文件夹

- 删除旧输入框模式切换、旧侧栏与名称弹窗，重写侧栏顶部 slothy chat / sloty coding 菜单；模式分别保留草稿、预算和任务列表，切换不取消运行。
- Coding 侧栏新增可折叠项目/子任务、创建和编辑弹窗、路径/仓库/任务数量详情及置顶；Chat 隐藏项目环境。桌面选择本机文件夹，浏览器通过完整路径表单附加。
- 项目持久化源文件夹与身份，新任务绑定所属项目目录；编辑不改变已有任务或审批恢复目标。Coding 权限单独配置，旧目录 API 保持兼容；见 ADR 0017。

### Coding Agent 模式

- slothy chat / sloty coding 模式真实配置系统提示、工具目录、上下文与运行预算。项目保存源文件夹，设置页保存修改权限、检查预设与时限。
- Infrastructure 增加目录浏览、文件读取、字面代码搜索、SHA256 校验的精确修改/写入和固定项目检查。修改与检查沿用单次人工审批，校验在审批之前；结果、输出、扫描与子进程等待均受限。
- 新任务绑定目录身份与权限，设置改变和重启不会重定向已有任务；所有模式继续完成后才保存记忆。新增临时文件、子进程、完整桌面审批/恢复及浏览器配置/模式用例；见 ADR 0016。

### 桌面布局与真实桥接

- Vue 深色三分区布局，复用官方 Logo、CSS 品牌变量，提供居中输入、项目/灵感、工具目录、TaskState JSON、工具/重试时间线、流式回答、审批与 Token 状态栏。
- 新增 desktop.py 产品组装根、pywebview 单请求桥接、回环 HTTP 预览、Workspace API/Service 与 SQLite 归属目录。复用 Runtime/Memory 原子接口，快速/进阶实际注入 Policy；缺失能力明确标为未接入。
- 新增所属用户的 inspect_run 展示投影，显式筛选字段，不暴露历史、原始快照、凭据和处理函数。桌面只调用已配置真实文本模型，不使用演示模型回退。
- 增加桌面集成与独立浏览器 E2E，验证项目/记忆持久化、工具链、重试、预算、日志、配色与响应式布局。说明见 docs/desktop-ui.md、ADR 0013。

### 分层 Context 与受控记忆

- 删除旧 Context 算法并保留公开兼容适配器；新增四层 LayeredContext、XML 信任边界、结构化 TaskState、全请求/输出预算与有序降级，Runner 公开接口不变。
- SQLite 外化长工具结果和滚动历史，快照只保存有界视图与结果引用；工具日志在提交前外化，恢复验证范围、原文摘要指纹与引用，保留既有幂等/用户审批语义。
- 受控 search_memory/get_result 支持混合检索、FTS5/BM25、实体过滤、时间衰减、去重、重排回退与实际页长游标；新增原子 MemoryAPI/MemoryService。
- DashScope embedding、chat、rerank 配置与能力隔离，摘要使用 chat 并计入输入包装；各通道独立超时与有限线程隔离，观察只输出安全计数。密钥仅从环境读取，模板键名同步且均使用占位符。
- 默认离线 main 验证新 Context，旧布局仍可显式验证；新增模型/SQLite/应用/恢复与安全回归测试、配置说明、迁移说明和 ADR 0012。

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
