# ADR 0011：Application 原子用例与独立演示组装

- 状态：已采纳
- 日期：2026-10-04
- 约束：[开发指南](../Slothy-Development-Guide.md)、[初始化指南](../Project-Initialization-Guide.md)
- 关联：[ADR 0007](0007-runner-module-entrypoints.md)、[ADR 0010](0010-runtime-snapshot-and-replay-safety.md)

## 问题

Core 已具备上下文、策略、事件和恢复，但 main 的验证入口不能承担产品服务。Presentation 需要稳定的操作、可序列化状态、审批与观察能力，同时不能取得 Core 实体、SDK 或原始快照。审批和执行的隐式串联还可能绕过对具体工具尝试的审阅。

## 决定

1. 保持现有目录，以 RuntimeAPI → 请求 DTO → RuntimeService → Core 实现应用入口。Application 只依赖自己的模块、Core 和标准库，具体提供方、数据库和执行器由外部组装根注入。
2. 创建、启动、查询、控制、决定审批和恢复分别为单一用例。创建不运行，审批不运行，恢复要求具体快照版本。同一 Run 使用独立 Runner/Context，只能有一个活动驱动。
3. API 成功/失败响应均为 JSON 数据，错误采用固定分类与文本。状态只暴露标识、计数、步骤、最终输出与审批标识；审批参数通过单独受归属检查的接口读取。API 不提供原始快照上传或运行时依赖替换。
4. 身份由宿主绑定，所有 Run 操作均验证归属。这里的 actor_id 是已认证身份的载体，不承担认证。Saved Run 只能由可信宿主确认归属后在 Service 登记；内存目录不能冒充持久所有权目录。
5. 执行保持同步，宿主负责工作线程调度。Application 对控制意图的转交不修改 Core 状态机；恢复交接期间保留意图，之后交给新 Run。Core 增加只读 `AgentRunner.current_run` 与 `Run.request_cancel()`：取消意图由驱动线程在检查点生效，原 `Run.cancel()` 直接取消行为兼容。`cancel_snapshot` 通过 Runtime 模块校验并取消未接管快照，不调用模型/工具。
6. Application 接收 Core 事件、显式映射 EventDTO，缓存有限历史并向宿主回调推送副本；未知字段不自动导出，Context preview 不导出。监听失败隔离，只记录计数。缓存 cursor 在当前 Service 内有效，Core sequence/generation 负责恢复关联；持久审计后续单独实现。
7. main 只组装依赖和验证流程，默认离线，实际模型用 `--live` 显式选择。通过相同 Application API 展示上下文压缩、重试、观察和暂停恢复。保留 run_calculation 演示兼容入口；产品不得依赖它。

## 后果与边界

- Application 接口可由未来 pywebview 桥接或其他 Presentation 适配，无需把业务逻辑搬到 main。
- 一次同步驱动包含多次外部调用，不是可回滚数据库事务。取消/超时无法强制停止已开始的任意 I/O；同一 Run 跨 Service/进程仍须由宿主保证一个驱动，存储 CAS 是版本保护，不是分布式租约。
- 事件回调同步调用，慢监听会延长执行；Presentation 必须快速入队并在 UI 线程处理。产品后台调度和持久事件存储不在本次接口实现中。
- 审批决定只存在内存，重建 Service 必须重新确认；Core 的一次尝试许可仍不持久化，遵循 ADR 0010。持久身份目录和设置服务尚未实现，不加入空占位接口。
- MCP 与 RAG 只形成 [后续计划](../plans/mcp-rag-plan.md)，本轮不引入 SDK、协议运行时、文档索引或向量数据库代码。

## 验证

应用单元测试检查原子操作、归属隔离、JSON 副本、稳定错误、审批/版本绑定、单驱动、观察者失败、缓存裁剪与恢复控制。架构检查阻止 Application 导入 Infrastructure/main/Presentation/SDK/SQLite。

集成测试采用真实计算执行器、假模型和临时 SQLite，验证新 Service 恢复不会重复已完成工具；main 默认离线验证长上下文、策略重试、观察及暂停恢复。全量 Core 回归继续使用假模型和假时钟，不访问真实 API。
