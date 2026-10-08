# 运行时事件

Runtime 在状态迁移和模型、工具调用边界发出提供方无关的事件。界面、日志和持久化通过 `EventSink` 协议接收事件，不需要侵入执行逻辑，也不需要轮询 `Run` 状态。

设计理由与失败处理策略见 [ADR 0003](decisions/0003-runtime-event-contract.md)。

## 订阅方式

```python
from slothy.core.events import EventBus, RunFailed, StepEnd, ToolCallEnd
from slothy.core.runtime import AgentRunner

bus = EventBus()
bus.subscribe(StepEnd, lambda event: print(event.outcome, event.duration_ms))
bus.subscribe(RunFailed, lambda event: print("失败：", event.error.error_code))

@bus.on(ToolCallEnd)
def report(event: ToolCallEnd) -> None:
    print(event.name, event.is_error, event.output_size)

runner = AgentRunner(model, registry, executor)
result = runner.run(user_input, context=context, events=bus)
```

订阅基类即可收到它的全部子类事件：订阅 `RunEvent` 会收到所有运行时事件，订阅 `ToolEvent` 会收到全部工具事件。`subscribe` 返回取消订阅的函数。

`RunTimeline` 是按顺序保存事件的最小实现，适合测试与外层转发：

```python
timeline = RunTimeline(bus)
runner.run(user_input, context=context, events=bus)

timeline.types()          # 事件类型顺序
timeline.first(StepEnd)   # 第一个指定类型的事件
timeline.of_type(Metric)  # 指定类型的全部事件
```

也可以不传 `events`，改为在创建 `Run` 时绑定接收端：

```python
runtime = Run(run_id=run_id, max_steps=8, events=bus)
runner.run(user_input, context=context, runtime=runtime)
```

## 事件类型

所有 27 个事件继承 `RunEvent`，携带 `run_id`、`sequence`、`step_number` 和 `occurred_at`；工具事件另有 `call_id`。正常执行中的 `sequence` 连续；恢复从最后持久化序号继续，`RunResumed.generation` 标明新的执行片段。快照与事件投递未组成事务，崩溃窗口可能缺失或重发事件。

| 类别 | 事件 | `event_type` | 关键字段 |
| --- | --- | --- | --- |
| 生命周期 | `RunStarted` | `run.started` | `max_steps`、`deadline_seconds` |
| | `RunCompleted` | `run.completed` | `steps`、`duration_ms` |
| | `RunFailed` | `run.failed` | `steps`、`duration_ms`、`error` |
| | `RunCancelled` | `run.cancelled` | `steps`、`duration_ms` |
| | `RunSuspended` | `run.suspended` | `reason` |
| | `RunResumed` | `run.resumed` | `generation` |
| | `StepStarted` | `run.step.started` | — |
| | `StepEnd` | `run.step.ended` | `outcome`、`duration_ms`、`tool_call_count` |
| | `StepTimeout` | `run.step.timeout` | `duration_ms`、`timeout_seconds` |
| | `StepLimitReached` | `run.step.limit` | `max_steps`、`requested_tool_calls` |
| 模型 | `ModelRequestStart` | `run.model.request_started` | `message_count`、`tool_count` |
| | `ModelResponded` | `run.model.responded` | `duration_ms`、`text_length`、`tool_call_count`、`usage` |
| | `TokenChunk` | `run.model.token_chunk` | `index`、`text` |
| | `ModelError` | `run.model.error` | `duration_ms`、`error` |
| | `LLMTimeout` | `run.model.timeout` | `duration_ms`、`error` |
| 工具 | `ToolCallStart` | `run.tool.call_started` | `name`、`argument_keys` |
| | `ToolCallEnd` | `run.tool.call_ended` | `name`、`duration_ms`、`is_error`、`output_size` |
| | `ToolProgress` | `run.tool.progress` | `name`、`completed`、`total`、`message` |
| | `ToolTimeout` | `run.tool.timeout` | `name`、`duration_ms`、`error` |
| | `ToolError` | `run.tool.error` | `name`、`duration_ms`、`error` |
| 状态/策略 | `ContextCompressed` | `run.context.compressed` | `tokens_before`、`tokens_after`、`messages_removed`、`messages_truncated`、`strategy`、`preview` |
| | `PolicyTriggered` | `run.policy.triggered` | `policy`、`decision`、`reason` |
| | `GuardrailBlocked` | `run.policy.guardrail_blocked` | `guardrail`、`call_id`、`name`、`reason` |
| | `ToolApprovalRequested` | `run.tool.approval_requested` | `request_id`、`call_id`、`name`、`attempt`、`reason` |
| | `ToolApprovalResolved` | `run.tool.approval_resolved` | `request_id`、`call_id`、`name`、`approved` |
| 观测 | `TokenUsage` | `run.observability.token_usage` | `usage`、`cumulative` |
| | `Metric` | `run.observability.metric` | `name`、`value`、`unit` |

`EVENT_TYPES` 提供完整的事件分类表，`LIFECYCLE_EVENTS`、`MODEL_EVENTS`、`TOOL_EVENTS`、`STATUS_EVENTS`、`OBSERVABILITY_EVENTS` 按类别分组。

所有事件当前都有发射方：生命周期事件由 `Run` 状态迁移发出；上下文、模型、工具和策略事件由对应模块入口发出，运行耗时由 `RunObservation` 记录。各模块通过 `EventEmitter` 共用 `Run.relay`，事件顺序和序列号契约不变。runner 只编排循环，职责划分见 [ADR 0007](decisions/0007-runner-module-entrypoints.md)。

## 事件顺序

```text
RunStarted
  StepStarted
    ContextCompressed?                                   # 上下文超预算时
    ModelRequestStart → TokenChunk* → ModelResponded → TokenUsage
      ToolCallStart
        PolicyTriggered? → GuardrailBlocked?             # 被拦截时，不调用执行器
        ToolProgress*                                    # 执行器上报进度时
      ToolCallEnd
    StepEnd → Metric(step.duration_ms)
RunCompleted → Metric(run.duration_ms)
```

- `StepEnd` 在一次步骤的终态发出，正常运行时每个步骤只出现一次；`outcome` 取值为 `completed`、`failed` 或 `cancelled`。
- 失败时先写 `StepEnd`，再写 `RunFailed`，最后写 `Metric(run.duration_ms)`；超时额外先写 `StepTimeout`，达到步数上限额外先写 `StepLimitReached`。
- 取消由 `Run.cancel()` 发出 `RunCancelled`，运行器在下一个检查点写出 `StepEnd(outcome=cancelled)` 后抛出 `RunCancelledError`。已经暂停的 Run 没有驱动循环，由取消入口直接结束步骤并保存终态。
- 步数上限：最后一步仍请求工具时，运行器拒绝执行这些调用并抛出 `StepLimitExceededError`，`Run` 进入 `FAILED`。
- 策略拦截不中断执行：`GuardrailBlocked` 之后是 `ToolCallEnd(is_error=True)`，随后把错误结果交回模型，运行继续。
- 同一个 Run 对象/执行片段只有一个 Run 级终态事件：`RunCompleted`、`RunFailed` 或 `RunCancelled`。可恢复的失败会从快照创建新对象，原对象保持终态。

## 暂停、恢复与审批

`Run.interrupt()` 在下一边界发 `RunSuspended(reason="interrupted")`，返回带快照的
暂停结果，不发失败事件。不可校验的工具尝试发 `ToolApprovalRequested`，再发
`RunSuspended(reason="approval")`，状态为 `WAITING_APPROVAL`，没有工具结束事件
或后续模型调用。宿主提交一次决定后发 `ToolApprovalResolved` 和 `RunResumed`；
同意进入工具安全校验，拒绝产生 `ToolCallEnd(is_error=True)`，结果交回模型。
审批事件不携带参数、原结果、幂等键或用户身份，具体审批内容从 `result.approval`
读取。审批类也继承 `ToolEvent`，Run 暂停/恢复继承 `RunLifecycleEvent`。
快照与一次性授权语义见 [Runtime 快照与恢复](runtime-recovery.md)。

## 上下文压缩

上下文模块在每次模型请求前通过 `get_windowed_messages()` 按预算准备消息；裁剪或工具结果缩短时发出 `ContextCompressed`。消息追加统一经 `context.conversation.add` 处理，runner 不再组装消息字典。正式系统与摘要器注入见 [Context System](context-system.md)。

```python
from slothy.core.context import InMemoryContext
from slothy.core.runtime import AgentRunner

window = InMemoryContext(token_budget=8192, system_prompt="你是一个简洁的助手。")
runner = AgentRunner(model, registry, executor, context=window)
```

- 默认策略为 `trim_oldest`：丢弃最早的完整单位，不切断工具结果与助手调用的配对，保留系统提示、最新用户消息和最新消息/工具往返。
- 系统提示永不裁剪；只有系统提示时请求只包含它。
- 令牌规模由 `TokenEstimator` 估算（默认 `HeuristicTokenEstimator` 按字符估算），只用于判断是否需要裁剪，不能用于计费。
- `InMemoryContext` 在配置计数器度量下执行硬预算：必要时缩短保留的工具结果。不可裁剪内容自身超限时抛出 `ContextBudgetExceededError`，不发出模型请求；旧 `ContextWindow` 保留软预算兼容行为。
- 没有实际移除、缩短或摘要消息时不发出事件。正式 Context 的 `preview` 只含计数，不含历史或工具结果内容。

## 策略与拦截

`ToolSession.tool_call` 在 `ToolCallStart` 之后、调用执行器之前经策略模块的 `check_tool_call` 入口做判定：

```python
from slothy.core.policy import PolicyEngine, PolicyVerdict, ToolNameRule, AllowlistRule

policy = PolicyEngine(
    rules=(
        ToolNameRule("shell*", PolicyVerdict.DENY, reason="禁止命令行"),
        AllowlistRule(frozenset({"add", "subtract"})),
    )
)
runner = AgentRunner(model, registry, executor, policy=policy)
```

- 第一条非 `ALLOW` 判定生效；没有规则介入时为默认允许，此时不产生任何策略事件。
- `DENY` 与 `ASK` 都拦截调用：不调用执行器，发出 `GuardrailBlocked`，并向模型返回 `is_error=True` 的结果。
- `ASK` 与 `DENY` 一样按规则拦截，理由文本说明该规则未接入审批；工具重放安全的 `WAITING_APPROVAL` 是独立流程。
- 规则只匹配工具名，不读取参数取值，因此参数不会进入事件或日志。
- 策略判定不替代执行器自身的参数校验与授权。

## 重试与无进展

运行韧性由 [Policy System](policy-system.md) 管理。模型的每次重试都会重新发出
`ModelRequestStart`，失败尝试发错误事件，重试前发
`PolicyTriggered(decision="retry")`；只有成功响应发用量。工具重试保留同一条
逻辑调用的开始/结束事件，失败尝试分别发错误事件。无进展终止发
`PolicyTriggered(decision="terminate", reason="no_progress")`，再进入唯一失败
终态。可恢复工具异常发 `PolicyTriggered(decision="return_error")`，随后产生
`ToolCallEnd(is_error=True)`。事件不含异常文本或工具结果。

## 工具进度

长任务执行器通过 `ToolExecutor.execute` 的可选回调上报进度：

```python
from slothy.core.tools import ProgressReport, ToolResult

class LongTaskExecutor(ToolExecutor):
    def execute(self, call, context, on_progress=None):
        for index in range(1, 4):
            if on_progress is not None:
                on_progress(ProgressReport(completed=index, total=3, message="处理中"))
        return ToolResult(output="完成")
```

- 回调只接受 `ProgressReport`：已完成计数、总数与阶段说明，不含工具参数或结果内容。
- 每次上报产生一个 `ToolProgress` 事件；调用结束后回调失效，延迟上报会被忽略。
- 没有事件接收端时不传入回调（`on_progress` 为 `None`），执行器可以跳过进度计算。
- 瞬时工具（如计算工具）忽略该参数即可。

## 错误信息

事件的 `error` 字段是 `ErrorInfo`，只包含：

- `error_code`：稳定的错误分类，取值包括 `run_timeout`、`step_timeout`、`step_limit_reached`、`run_cancelled`、`llm_timeout`、`tool_timeout`、`unexpected_timeout`、`runtime_error`、`run_failed`、`context_error`、`context_budget_exceeded`、`no_progress`、`model_transient_error`、`snapshot_error`、`snapshot_conflict`、`idempotency_conflict`、`tool_execution_unknown`。
- `error_type`：异常类名，仅在核心层没有该异常的稳定分类时提供。

原始异常文本不会进入事件，因此事件里不会出现提供方请求细节或本地路径；`RunFailed` 的异常仍照常向 `runner.run` 的调用方传播。

提供方和执行器可以抛出核心层的错误分类，让事件给出准确原因：

```python
from slothy.core.events import LLMTimeoutError, ToolTimeoutError
```

## 观测指标

| 指标名 | 含义 | 发出时机 |
| --- | --- | --- |
| `step.duration_ms` | 单个步骤从开始到终态的耗时 | `StepEnd` 之后 |
| `run.duration_ms` | 整次执行从开始到终态的耗时 | Run 级终态事件之后 |

`TokenUsage` 的 `usage` 是本次模型调用的用量，`cumulative` 是本次 Run 的累计用量，两者都来自提供方上报，核心层不做估算。

## 流式分片

`ModelSession.model_call` 在调用模型时传入可选的 `on_chunk` 参数。MiMo 适配器收到该参数时改用流式请求，逐段回调文本增量，模型模块随即发出 `TokenChunk`；未收到该参数时保持一次性请求，不产生 `TokenChunk`。新 Run 的 Session 独立计数；恢复时还原已持久化的分片序号和累计用量。未完成请求可能重新调用，跨恢复的文本投递不保证去重。

提供方可以忽略该参数（表示不支持流式），此时也不会产生 `TokenChunk`。自定义提供方按同样方式接入：

```python
def generate(self, messages, **kwargs):
    on_chunk = kwargs.get("on_chunk")
    ...
    if on_chunk is not None:
        on_chunk(delta_text)
```

适配器需要负责把工具调用分片拼装成完整的 `ToolCall`（按 `index` 累积标识、名称与参数），因为 `ModelProvider.generate` 仍然一次性返回完整的 `ModelResult`。

## 失败隔离

Application 已提供 Core 事件到 JSON DTO 的显式映射、有限历史缓存、所属用户订阅与监听失败计数，见 [Application API](application-api.md)。Presentation 可绑定快速返回的转发回调，不必直接依赖 Core 对象；main 的完整演示通过此接口观察上下文、策略、工具和耗时。

观察者抛出的异常不会影响运行结果：事件总线会隔离该异常、继续调用其他处理器，并把 `EventDeliveryFailure`（事件类型、序列号、异常类名、消息）记入 `EventBus.failures`。运行本身不会因此失败或重试，监控故障需要外层主动检查 `failures`。

没有接收端时运行器不产生任何事件，行为与不传 `events` 的 0.1.0 一致。

## 分层 Context 指标

LayeredContext 的压缩继续发 ContextCompressed，strategy 为 layered，preview 只含移出/缩短计数。每个模型请求前额外发出 Metric：context.input_tokens（含原生工具定义）、context.memory_topk、context.summary_failures。计数来自 Context 的安全报告，不包含历史、查询、任务状态或工具原文；应用沿用已有 Metric DTO 映射。层计数和检索通道分类可由外层 observer 消费，观察者失败不改变运行结果。旧适配器没有新报告时，事件序列保持兼容。
