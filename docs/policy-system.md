# Policy System

`Policy` 统一管理运行约束。Runner 只编排循环和生命周期，通过
`PolicySession.should_terminate()` 执行策略决定；步数、时限、失败处置、重试和
无进展检测归 `core/policy`。更换策略不需要修改 Runner。

## 注入与组合

```python
from slothy.core.policy import (
    DefaultPolicy, RetryPolicy, SafetyPolicy, TimeoutPolicy,
    ToolNameRule, PolicyVerdict,
)
from slothy.core.runtime import AgentRunner

runner = AgentRunner(model, registry, executor, policy=DefaultPolicy(max_steps=5))

runner = AgentRunner(
    model, registry, executor,
    policy=TimeoutPolicy(DefaultPolicy(max_steps=20), timeout_seconds=30),
)

policy = RetryPolicy(
    SafetyPolicy(
        TimeoutPolicy(
            DefaultPolicy(20), timeout_seconds=30,
            step_timeout_seconds=10, model_timeout_seconds=5,
            tool_timeout_seconds=3,
        ),
        rules=(ToolNameRule("delete_*", PolicyVerdict.DENY),),
        no_progress_limit=3,
        return_tool_errors=True,
    ),
    max_retries=2,
    retry_tools=frozenset({"lookup"}),
)
runner = AgentRunner(model, registry, executor, policy=policy)
```

配置不可变。重试次数、进展指纹和消息不保存在策略配置里，每个 Run 的
`PolicySession` 独立；复用 Runner 不会继承上一轮的计数。

## 契约

| 入口 | 返回 | 职责 |
| --- | --- | --- |
| `limits` | `PolicyLimits` | 步数、总/步骤/模型/工具时限 |
| `should_terminate(snapshot)` | `Termination` 或 `None` | 决定终止类型，不操作 Run |
| `on_error(failure)` | `RAISE` / `RETRY` / `RETURN_ERROR` | 处理本次尝试失败 |
| `timeout_for(operation, snapshot)` | 剩余秒数或 `None` | 计算最短剩余预算 |
| `decide(tool_request)` | `PolicyDecision` | 工具 `ALLOW` / `DENY` / `ASK` |

`PolicySnapshot` 只包含步骤、耗时、请求工具数和连续重复计数。
`FailureContext` 包含操作类型、异常、尝试编号、工具名、是否已交付流式文本及
是否有工具重放校验。
异常只供策略内部判断，不进入事件。自定义策略可实现协议，或继承
`WrappedPolicy` 覆盖入口。模型路由可在模型模块内扩展，无需 Runner 理解价格
或提供方；本轮没有实现价格表或模型选择算法。

## 行为

- `DefaultPolicy(max_steps=8)`：默认异常原样抛出，不隐式重试。最后一轮可以
  直接回答；若仍请求工具，则停止，不执行无法反馈给模型的调用。
- `TimeoutPolicy`：嵌套时限取更短值。总时限包含摘要、模型、工具与重试。
  取消优先于时限，总时限优先于步骤时限。超时结果不会进入模型上下文。
- `RetryPolicy(max_retries=2)`：最多额外尝试两次。默认仅重试 `ConnectionError`、
  `TransientModelError`、`LLMTimeoutError`、`ToolTimeoutError`；可注入
  `retryable_errors`。重试在同一步内进行，不增加轮次、不重放已成功的其他工具，
  不重置总、步骤或逻辑调用预算。重试立即进行，没有后台等待或退避。
- `SafetyPolicy(no_progress_limit=3)`：连续三次相同工具往返触发 `NoProgressError`。
  比较工具名、参数、结果和错误标志，忽略变化的调用 ID 和助手措辞。
  结果变化视为进展；`None` 关闭检测。这不是语义层面的任务进展判断。

`DefaultPolicy` 不自动重试；注入 `RetryPolicy` 后，具有重放声明的工具每次尝试
均通过工具日志校验：`IDEMPOTENT` 可安全重放，`KEYED` 查询稳定键的执行凭据，
无法确认的结果与 `UNVERIFIABLE` 等待用户审批。`retry_tools` 作为旧接口，表示
调用方保证未声明工具可重复执行，包括超时后结果不明的情况；它不能覆盖显式的
非幂等声明。`ToolResult(is_error=True)` 是受控结果，不会自动重试。
已交付流式文本的模型失败不自动重试，避免重复输出。
流式和进度回调在每次尝试结束后失效。

`return_tool_errors=True` 将重试耗尽后的工具异常转为固定错误说明和安全分类，
供模型继续处理；默认仍抛出异常。取消和运行时终止不能被恢复策略吞掉。
`ASK` 继续按工具规则拦截。工具重放的审批等待与持久恢复见
[Runtime 快照与恢复](runtime-recovery.md)，独立于通用 ASK 的语义。

## 同步超时边界

本实现是**协作式超时**。Run 在调用边界终止，无法强制中断正在执行的同步
提供方、执行器或摘要器。若工具阻塞一分钟，三十秒时限只能在它返回后检查，
不能声称在第三十秒强制结束。

模型接收 `generate(..., timeout=剩余秒数)`，MiMo 用于 SDK I/O 超时。
工具接收 `ToolContext.timeout_seconds`，执行器应设置自己的底层 I/O 超时。
提供 `get_tool(name)` 的注册表还会传递 `ToolDefinition.timeout_seconds`，
它与策略时限取更短值；旧的只有 `definitions()` 的注册表仍可用。
不遵守时限的实现只在返回后检查，I/O 超时也不等于进程的硬截止时间。

真正强制中断阻塞操作需要 Infrastructure 的隔离执行与终止实现，并明确
序列化、回调传递、内存状态和已经发生的外部副作用。本轮未实现进程隔离，
也不采用超时返回后仍继续运行的后台线程。

MiMo 禁用 SDK 内部重试，由 Policy 唯一控制尝试次数；连接错误、429 和 5xx
映射为 `TransientModelError`，SDK 超时映射为 `LLMTimeoutError`。
认证、参数等永久性故障默认不重试。失败的 SDK 流也会关闭。

## 兼容与事件

`AgentRunner(..., max_steps=5)` 仍有效，原 `PolicyEngine` 仍可注入。
显式 `max_steps` 与新策略上限矛盾时拒绝构造。`run(...)`、
`ToolExecutor.execute(...)` 和 `RunnerResult` 不变。
既有 `Run(deadline_seconds=..., step_timeout_seconds=...)` 的限制与 Runner
策略取更短值；运行 ID 和上限仍须匹配。Run 也可绑定 `policy` 独立使用。
Runner 使用自身注入的策略，Run 保留状态及生命周期事件职责，每个执行片段只有
一个终态。恢复创建新 Run 对象并保留进展、尝试次数和已记录耗时，不计入离线或
审批等待时间；原对象的终态不改变。

每次模型尝试发 `ModelRequestStart`；失败发错误事件，重试前发
`PolicyTriggered(decision="retry")`。仅成功响应产生用量事件，未报告的失败
尝试用量无法推算。工具重试属于一条逻辑调用，一个 `ToolCallStart`、每次失败的
错误事件、最终一个 `ToolCallEnd`；未恢复的失败没有结果事件。
事件不含异常文本、参数取值或结果原文。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts/demo_policy_system.py
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_*.py
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_*.py
```

演示使用同一个 `AgentRunner` 类型、假模型与假时钟，无网络、无等待：五次模型 /
四次工具后步数终止；三次模型 / 两次工具、假时钟三十秒后时限终止；两次故障后
重试恢复；三次重复往返后无进展终止。此验证不能证明阻塞调用的硬中断。
