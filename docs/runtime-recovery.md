# Runtime 快照、恢复与工具重试

Runtime 现在保存执行游标和工具执行日志。`AgentRunner.run()` 执行至完成、失败或
暂停；`resume()` 从快照创建新的 Run 对象继续。Runner 仍是固定入口，消息转换、
模型调用、重试判断和工具重放校验分别归 Context、Model、Policy 和 Tool 模块。
设计理由见 [ADR 0010](decisions/0010-runtime-snapshot-and-replay-safety.md)。

## 接入持久化

```python
from slothy.core.policy import RetryPolicy
from slothy.core.runtime import AgentRunner
from slothy.core.tools import ToolContext
from slothy.infrastructure.persistence.runtime_store import SQLiteSnapshotStore

store = SQLiteSnapshotStore("data/runtime.sqlite")
runner = AgentRunner(model, registry, executor,
                     policy=RetryPolicy(max_retries=2), snapshot_store=store)
context = ToolContext("unique-run-id")
result = runner.run("执行任务", context=context)

# 中断或进程重启后，重新注入相同模型契约、工具定义、执行器和策略配置。
snapshot = store.load(context.run_id)
restored_runner = AgentRunner(model, registry, executor,
                             policy=RetryPolicy(max_retries=2), snapshot_store=store)
result = restored_runner.resume(snapshot, context=context)
```

不配置存储时使用内存快照，同一 Runner 中可恢复暂停并拒绝过期版本。
跨进程恢复、跨 Runner 的版本冲突和取消校验需要共享持久存储。宿主须为新任务
生成新的 `run_id`；持久存储会拒绝用同一 ID 覆盖已有运行。
恢复使用相同轮数上限，并操作返回的当前 `result.run` 发起后续取消。

`Run.interrupt()` 请求在下一调用边界暂停，返回 `RunnerResult`，其
`run.status == SUSPENDED` 且带有 `snapshot`。同步调用不会被强行打断。
`Run.cancel()` 是不可恢复的终止，等待审批时也会保存取消记录并结束步骤。
调用方应检查状态，不能把任何返回的 `RunnerResult` 都当作任务成功。

## 快照范围与检查点

`RuntimeSnapshot` 是版本化的有限 JSON；支持 `to_json()` / `from_json()` 和
`to_dict()` / `from_dict()`。不会序列化处理函数、SDK 客户端、事件接收端或回调。

| 数据 | 保存内容 |
| --- | --- |
| Run / Step | ID、状态、步骤和调用 ID、已记录耗时、时限、恢复代数、事件序号 |
| Context | 完整历史、压缩后的活动窗口、系统提示和 token 预算 |
| 执行游标 | 当前模型/工具/步骤结束/最终回答阶段、模型响应、批次位置 |
| 工具日志 | 原请求、实现版本、安全声明、幂等键、指纹、尝试次数、执行状态和结果 |
| Policy / Model | 进展指纹与当前往返、重试次数、逻辑调用耗时、已报告用量、分片序号 |
| 审批 | 待审批请求及历史决定的审计记录；不保存可再次消费的授权 |

执行顺序为：保存工具执行意图 → 调用执行器 → 保存工具结果 → 写入 Context 并
推进批次游标。写前保存失败时不调用工具。结果已保存但尚未推进游标时直接复用
结果；已提交的批次前缀不再执行。Context、步骤 ID、请求指纹和游标不一致时
拒绝恢复。SQLite 存储用事务比较 `expected_revision`，防止旧快照覆盖新版本。

恢复保留已记录的预算和自动重试次数，不计入暂停与进程离线的等待时间。
显式调用 `resume()` 允许一次新的安全尝试，自动重试不会重新获得一整份额度。
普通外部异常产生的失败片段可恢复；原 Run 对象仍保持失败，恢复对象的
`generation` 增加。取消、总/步骤超时、步数上限、无进展和快照错误不直接恢复。
存储错误时应读取最后成功提交的检查点，再按工具重放规则处理未知调用。

摘要器、计数器和其他配置须重新注入。内置 `InMemoryContext`、旧 `ContextWindow`
支持快照；自定义 Context 要提供 `snapshot_state()`、`restore_state(data)` 和
`validate_pending_exchange(response, index)`，校验助手请求与已提交结果。
不支持快照的旧 Context 仍可正常运行，但不能配置持久存储或进入审批等待。

快照包含原始对话、工具参数与结果，宿主需要管理其访问和保留期限，不能作为
普通事件日志公开。`ToolContext.metadata` 不进入快照；身份、权限与必要的外部
关联信息由可信宿主恢复时重新提供。

## 工具重放安全声明

安全声明由可信工具注册方设置，不接受模型参数覆盖，也不出现在模型工具 Schema。

| `ReplaySafety` | 行为 |
| --- | --- |
| `IDEMPOTENT` | 明确保证重复执行安全；可由 RetryPolicy 重试，也可恢复未知尝试 |
| `KEYED` | 非幂等操作；每次进入执行器前查询相同键的执行凭据 |
| `UNVERIFIABLE` | 每次尝试之前都等待用户审批，包括首次执行 |
| `UNSPECIFIED` | 兼容旧工具的首次调用；失败后重新执行必须审批 |

```python
from slothy.core.tools import ReplaySafety, ToolRegistry, tool

@tool(replay_safety=ReplaySafety.IDEMPOTENT)
def lookup(key: str) -> str:
    """读取已有数据。"""
    return read_existing_data(key)

@tool(replay_safety=ReplaySafety.KEYED, execution_version="1")
def create_order(order_id: str) -> str:
    """创建指定订单。"""
    return create_order_in_backend(order_id)

registry = ToolRegistry()
registry.register([lookup, create_order])
```

`ToolDefinition` 和 `tool_from_pydantic()` 也接受这些字段。未完成调用在恢复时
要求实现版本和安全声明一致，改变语义须更新 `execution_version`；已完成结果
仍按原请求复用。已有计算工具声明为 `IDEMPOTENT`。

`RetryPolicy` 默认针对临时故障有界重试，工具尝试仍须通过重放校验。
`ToolResult(is_error=True)` 是结果，不自动重试。旧 `retry_tools` 作为显式可信的
幂等声明继续支持未声明工具，不能覆盖 `KEYED` 或 `UNVERIFIABLE`。

## 非幂等工具的键与校验

运行时对工具名、实现版本和规范化参数计算指纹，再结合
`run_id + step_number + call_id + fingerprint` 生成稳定键。相同逻辑调用的重试和
恢复沿用同一键；参数变化、不同 Run、步骤或调用 ID 不共享键。
执行器通过 `ToolContext.idempotency_key` 和 `request_fingerprint` 获取它们。

执行器可实现 `IdempotencyVerifier.verify_idempotency(call, context)`：

| `IdempotencyCheck.status` | 运行行为 |
| --- | --- |
| `NOT_STARTED` | 已证明该键未执行，可进入受控执行器 |
| `COMPLETED` | 必须附带原 `ToolResult`；直接复用，不再次执行 |
| `UNKNOWN` | 执行中、凭据丢失或不能确认；进入审批等待 |

缺少校验器、校验故障或返回无效结果同样等待审批。键与参数冲突抛出
`IdempotencyConflictError`，用户同意也不能覆盖绑定冲突。`NOT_STARTED` 必须是
可信业务后端的判断；执行前还要原子占用该键，避免“先查询，再同时执行”的竞态。

提供 `KeyedToolExecutor` 和 `SQLiteIdempotencyLedger` 作为本地适配器：

```python
from slothy.infrastructure.app_tools.idempotency import (
    KeyedToolExecutor, SQLiteIdempotencyLedger,
)

executor = KeyedToolExecutor(
    controlled_executor, SQLiteIdempotencyLedger("data/tool-keys.sqlite"),
)
```

适配器保存“占用 → 副作用 → 完成凭据”。重启后有完成凭据时复用结果；
副作用已提交而完成凭据尚未提交时仍是 `UNKNOWN`，不会自动重放。占用令牌可阻止
旧执行者覆盖新尝试的凭据。它不能让任意外部副作用与 SQLite 原子提交。

生产适配器应把同一键传给支持去重的业务服务，或把业务修改与凭据放在同一事务。
订单等业务标识还须在业务层唯一约束：运行时键只去重同一逻辑调用，不把模型新发起的
另一次调用或另一个 Run 自动识别为相同业务操作。

## 等待用户决定

不可校验的尝试返回 `run.status == WAITING_APPROVAL`，停止后续工具及模型调用。
这是一处可持久化等待点，不占用阻塞线程或自动批准。
`result.approval` 包含请求 ID、工具名、具体参数、指纹、尝试编号和原因；宿主向
用户展示这些内容。未知结果时须说明此前副作用可能已经发生，再次执行可能重复。

```python
from slothy.core.tools import ApprovalDecision

request = result.approval
# approved 与 actor 来自宿主验证过的真实用户决定，不从模型输出读取。
decision = ApprovalDecision(request.request_id, approved=user_approved,
                            actor=authenticated_user_id)
result = runner.resume(result.snapshot, context=context, approval=decision)
```

同意只允许当前请求的一次尝试；拒绝产生受控错误结果交回模型，不调用工具。
未提交决定时继续等待。错误 ID、旧版本或已消费决定被拒绝。批准后再次中断且
结果不明时必须重新校验或重新审批；历史审计不授予永久权限。
`actor` 字符串用于审计，不提供身份认证，宿主仍负责鉴权和绑定当前待审批请求。
桌面原型已接入本次尝试的批准、拒绝与独立恢复操作，见[桌面说明](desktop-ui.md)。既有 `PolicyVerdict.ASK` 仍按规则拦截处理，此等待流程
针对工具执行安全，未改变通用策略 ASK 的语义。

产品宿主现在可通过 [Application API](application-api.md) 分别查询审批、记录批准/拒绝、恢复执行。身份由可信宿主绑定，审批记录和恢复为独立操作；桌面桥接复用这些接口。Core 的 `current_run` 跟踪新一代执行，`request_cancel()` 由驱动线程在检查点处理；`cancel_snapshot()` 可在不调用模型/工具的情况下取消已保存 Run。

## 验证与边界

```powershell
.\.venv\Scripts\python.exe scripts/demo_runtime_recovery.py
.\.venv\Scripts\python.exe scripts/demo_runtime_recovery.py --decision deny
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_runtime_snapshots.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_runtime_recovery.py -v
```

演示只写临时 SQLite 文件，无网络；默认展示凭据复用与未知结果阻塞。
`--decision` 仅模拟示例宿主的决定。测试覆盖进程对象重建、批次恢复、写前保存
失败、凭据提交窗口、一次性审批、旧版本、取消及预算保留。

同一 Run 须由一个活动驱动者执行。CAS 和键占用不替代分布式执行租约，恢复前应
结束旧执行者；审批未知结果也不能撤回旧执行者已经发生的副作用。
快照保存与事件投递没有事务性 outbox，崩溃窗口可能缺失或重发事件。
事件序号从最后提交点继续，恢复代数区分执行片段。
未完成的模型请求可能重新调用，已交付流式文本不能保证跨恢复去重；已持久化的
报告用量继续累计，未报告用量和最后检查点后的耗时无法精确还原。
