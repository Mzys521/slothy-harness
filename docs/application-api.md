# Application Runtime 接口

状态：已实现同步 Python 接口。遵循 [开发指南](Slothy-Development-Guide.md) 和 [初始化指南](Project-Initialization-Guide.md) 的 API → Service → Core 关系。设计记录：[ADR 0011](decisions/0011-application-api-and-demo-composition.md)。

## 分层与组装

```text
Presentation 的 Python 桥接
  → application/api/runtime_api.py       请求 DTO、稳定方法、JSON 错误响应
  → application/services/runtime_service.py  用例、运行归属、单驱动保护、Core 调用
  → Core AgentRunner / Run / SnapshotStore / ToolRegistry

Core 事件 → application/services/observation.py → EventDTO → Presentation 回调

main.py（独立演示组装根）
  注入 Context、Policy、模型、执行器和 SnapshotStore
Infrastructure 实现 Core 接口，Application 不导入 Infrastructure 或 main
```

`RuntimeService(runner_factory, registry, *, snapshot_store=None, event_capacity=1000)` 由宿主注入依赖。工厂每次返回尚未执行的独立 Runner；显式注入 Context 时也必须独立。工具目录与该工厂的受控执行器应使用同一组定义。配置快照存储时，工厂必须注入同一个存储对象。模型、策略、令牌预算、工具允许范围均由组装根设置，不能由模型请求或前端提交 Python 对象替换。

`RuntimeAPI(service, *, actor_id)` 的身份由可信宿主绑定。一份 Service 可为不同身份提供 API，但查询、控制、审批和事件只访问该身份所属的 Run；越权与不存在均返回 `run_not_found`。这提供归属检查，**不实现登录或认证**；产品宿主必须先完成身份认证，不能从客户端声明的 `actor_id` 取值创建 API。当前单用户演示绑定 `demo-user`。

## 原子操作

“原子”指每个入口处理一个用例，没有创建后自动运行、批准后自动恢复等隐式串联。执行和恢复可能包含多次模型/工具调用，不承诺外部副作用可回滚。

| 方法 | 请求字段 | 行为 / 响应 data |
| --- | --- | --- |
| `create_run` | `user_input` | 创建 IDLE Run，返回 RunDTO；不调用模型或工具 |
| `execute_run` | `run_id` | 驱动已创建的 Run 至完成、暂停、审批等待或失败 |
| `start_run` | `run_id` | `execute_run` 的同义入口，仍须先创建 |
| `get_run` | `run_id` | 读取 RunDTO |
| `list_runs` | 可选 `offset=0, limit=100` | 只列出调用者的 RunDTO，按登记顺序分页 |
| `cancel_run` | `run_id` | 取消空闲/暂停 Run，或对进行中的 Run 请求协作式取消 |
| `interrupt_run` | `run_id` | 对进行中的 Run 请求在检查点暂停；终态不能暂停 |
| `resume_run` | `run_id, expected_revision` | 用当前快照恢复新一代 Run；有待审批工具时须先作决定 |
| `get_approval` | `run_id` | 稳定等待时读取具体 ApprovalDTO，含工具参数副本 |
| `approve_tool` | `run_id, request_id, expected_revision` | 记录批准一次尝试的决定；不执行、不恢复 |
| `reject_tool` | 同上 | 记录拒绝决定；下一次恢复将错误结果交回模型 |
| `list_tools` | 空对象或省略 | 返回工具目录 DTO；无处理函数、执行器或 SDK 对象 |
| `get_events` | `run_id`，可选 `after=0, limit=100` | 读取 EventPageDTO，用于历史查看或推送断续后的补读 |
| `subscribe_events` | `run_id`，宿主 Python 回调为独立参数 | 返回 `subscription_id`；回调收到 JSON 数据副本 |
| `unsubscribe_events` | `run_id, subscription_id` | 返回 `removed` |

请求为字典，缺字段、未知字段、空字符串和布尔值冒充整数均被拒绝。输入文本上限 100000 字符，标识上限 128 字符，分页 limit 为 1–200，快照版本为正整数。超过当前事件范围的游标返回 `invalid_request`。

Python 回调由 Presentation 绑定并负责线程切换及桥接转发，不能由网页上传可执行代码。`subscribe_events` 仅推送订阅之后的事件；已有事件通过 `get_events` 查询。宿主应解除不再使用的订阅。

## 响应契约

```json
{"ok": true, "data": {"run_id": "...", "status": "idle", "busy": false}}
```

```json
{"ok": false, "error": {"code": "approval_required", "message": "请先批准或拒绝待审批工具。", "run_id": "..."}}
```

以上成功响应仅列出示意字段，实际 `RunDTO` 包括：标识、Core 状态、busy、步骤数量及步骤 DTO、最大步骤数、耗时、generation、snapshot_revision、最终 output、error_code、approval_request_id、approval_decision、取消/暂停请求标记、事件游标和监听失败计数。它不包含原始输入、上下文消息、工具结果历史或快照内容。步骤 DTO 只含编号、状态、调用 ID 和耗时。

`ApprovalDTO` 包括请求 ID、Run/步骤/调用标识、工具名、指纹、尝试编号、原因、参数、快照版本及待消费决定。参数仅在所属用户请求此接口时提供，以便实际审阅；普通状态与事件不包含参数值。决定中的 actor 来自已绑定的宿主身份，客户端不能提交 actor、参数替换、指纹替换或批准额度。

常见应用错误包括 `invalid_request`、`run_not_found`、`run_exists`、`run_busy`、`invalid_state`、`no_pending_approval`、`approval_required`、`approval_conflict`、`approval_already_decided`、`snapshot_conflict`、`invalid_configuration`。Core 超时、步数、无进展、幂等和快照错误映射为稳定分类；未知执行异常为 `execution_failed`，未知应用异常为 `internal_error`。不会将底层异常消息、SDK 响应或堆栈放入错误响应。失败后可通过 `get_run` 查询保留的状态。

## 执行、控制与审批

执行和恢复同步阻塞至本次驱动结束。Service 不创建隐式后台任务；桌面宿主应在工作线程驱动，按自身 UI 调度机制消费回调。每个 Run 只允许一个驱动操作，重复启动/恢复得到 `run_busy` 或 `invalid_state`。内部锁不覆盖模型或工具阻塞调用，其他线程仍可查询、取消或请求暂停。

进行中的取消通过 `Run.request_cancel()` 记录意图，在驱动线程检查点迁移状态并保存，避免控制线程并发写运行游标。恢复交接期间暂存控制意图，在 `RunResumed` 接入新 Run 时转交。`AgentRunner.current_run` 提供当前对象，原 Run 的历史终态不被改写。`cancel_requested` 表示请求尚待处理；已经开始的同步 I/O 不会因此被强制打断。暂停、超时也保留 Core 的协作式保证。

审批绑定 `request_id + snapshot_revision`。旧版本、错误请求及重复决定均拒绝。批准保留在 Service 内存，直到显式 `resume_run` 消费一次；每次驱动开始时就移除暂存决定。崩溃或新建 Service 后不会继承尚未消费的授权。Core 在消费决定时保存审计，不持久化可重复使用的批准许可。新一次不可校验尝试仍需新审批。原 PolicyEngine 的 `ASK` 保持原有拦截语义；本接口处理 ToolJournal 的重放安全审批。

## 观察与恢复

事件 DTO 使用显式字段表，包含应用缓存 cursor、Core sequence、Run 标识、事件类型、步骤号、时间、当前 Core status、generation 和安全 payload。Context 压缩只输出计数和策略，省略 preview。模型流式文本用于所属用户展示；上下文原文、工具参数值、工具结果原文、密钥与快照不进入普通事件。调用者修改响应或监听器修改收到的字典不影响缓存。

缓存默认每个 Run 保留最后 1000 个事件；`EventPageDTO` 返回 `events, next_cursor, oldest_cursor, truncated, has_more`。`truncated` 表示请求游标之前有历史已淘汰。cursor 是当前 Service 内存中的定位，重建 Service 后从 0 开始；Core sequence 与 generation 用于关联恢复事件，不能把缓存当作持久审计。单个监听器失败隔离并增加计数，后续监听器仍收到事件。监听器应快速返回，缓慢回调仍会延长同步驱动时间。

Service 的运行归属目录、事件缓存和未消费审批决定当前仅在内存中。跨进程的 Runtime 数据可通过注入 SQLiteSnapshotStore 保存，但产品的归属目录持久化尚须后续实现。重启后由**可信宿主**先从其可靠目录确定所有者，再调用：

```python
service.register_saved_run(saved_run_id, owner_id=authenticated_owner_id)
```

此操作只加载并登记，不执行。它不是前端 API，也不能根据用户猜测的 Run ID 自动认领所有权。登记后的查询、审批和 `resume_run` 仍通过 API。取消尚未接管的快照使用 Core 的 `cancel_snapshot`，验证恢复数据后写入取消终态，不调用模型或工具。持久数据损坏、配置变更或版本冲突会给出受控错误。

## 最小调用示例

```python
from slothy.application.api import RuntimeAPI
from slothy.application.services import RuntimeService

# runner_factory、registry、store 由产品组装根注入 Core 接口。
service = RuntimeService(runner_factory, registry, snapshot_store=store)
api = RuntimeAPI(service, actor_id=authenticated_owner_id)
created = api.create_run({"user_input": "计算任务"})
run_id = created["data"]["run_id"]
subscription = api.subscribe_events({"run_id": run_id}, presentation_forward_event)
result = api.execute_run({"run_id": run_id})
# 等待审批时先 get_approval 展示具体操作，收到用户明确决定后 approve_tool/reject_tool。
# 宿主随后单独调用 resume_run，并带上查询得到的 snapshot_revision。
api.unsubscribe_events({"run_id": run_id, **subscription["data"]})
```

验证位置：`tests/unit/test_application_runtime.py`、`tests/integration/test_application_assembly.py`。当前交付不包含 HTTP 服务、桌面桥接、设置存储或后台调度；这些适配层将调用现有 API，不能移入 main 或让 Presentation 直接操作 Core。
