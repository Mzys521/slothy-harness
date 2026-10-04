# 0007 Runner 通过固定入口编排领域模块

## 背景

`runner.py` 同时处理消息格式、上下文压缩、模型调用与流式回调、工具策略、工具进度和错误事件。领域模块每次演进都需要修改循环文件，运行生命周期与模块内部细节交织。

## 决策

运行器只负责 Run/Step 生命周期、模型调用次数上限、工具调用前后的协作式检查，以及把异常向调用方传播。其余逻辑回到所属模块，每个领域通过固定的调用函数接入。

| 所属模块 | 集成入口 | 职责 |
| --- | --- | --- |
| `core/context/conversation.py` | `add(message, conversation=None, ...)` | 初次创建窗口，后续追加用户输入、模型响应或工具结果；`Conversation.messages` 在请求前准备预算并发出压缩事件 |
| `core/model/session.py` | `ModelSession.model_call(messages, tools)` | 调用提供方、流式分片、模型错误/超时分类、Run 内累计用量 |
| `core/tools/session.py` | `ToolSession.tool_call(call, context)` | 工具开始/结束事件、经策略入口判断、调用抽象执行器、工具进度与异常分类；`definitions` 属性提供模型可见定义 |
| `core/policy/evaluation.py` | `check_tool_call(policy, call, run_id, events)` | 判定与策略事件；允许时返回 `None`，拦截时返回可安全交给模型的错误说明 |
| `core/events/emitter.py` | `EventEmitter.emit(event)` | 把模块事件交给共享中继，统一边界耗时计算 |
| `core/runtime/observation.py` | `RunObservation` | 启动前绑定 Run 中继，记录步骤/运行耗时 |

模型与工具 Session 每次 Run 新建。Context 默认也是每次 Run 新建；显式提供 `ContextWindow` 时仍直接写入该窗口。模块使用同一个 `EventEmitter`，最终复用 `Run.relay` 的同一序列号空间。模型模块只接收检查函数，不导入或操作 Run 状态。

循环的领域调用形态如下；Run 的状态迁移、步数限制及检查点由 runner 包围这些调用：

```python
conversation = add(user_input, events=observation.events)
model = ModelSession(provider, observation.events, state.check_active)
tools = ToolSession(registry, executor, policy, observation.events)
definitions = tools.definitions

# 每个步骤：
response = model.model_call(conversation.messages, definitions)
if response.tool_calls:
    add(response, conversation)
    for call in response.tool_calls:
        result = tools.tool_call(call, context)
        add(result, conversation, call_id=call.call_id)
```

## 理由

固定入口隐藏消息和事件的转换细节；模型、工具和策略能够独立测试或修改。注册表继续只保存定义和处理函数引用，参数校验及实际权限判断仍由执行器负责，具体 SDK 和外部能力仍留在 Infrastructure。

## 备选方案

把辅助函数搬到一个公共 `utils` 文件只能缩短 runner，不能建立领域归属。增加以字符串选择操作的通用模块分发器会隐藏输入、返回值和错误语义。本次使用明确的领域入口与每次 Run 的局部状态。

## 影响与兼容性

- `AgentRunner` 构造参数、`run`、`RunnerResult`、`Run` 和 `ToolExecutor.execute` 的调用方式保持兼容，事件类型、负载与顺序保持兼容；原先从 runner 导入的指标常量继续可用。
- 模型响应后先检查取消与时限，再发出用量事件；最后一步请求工具仍直接失败，不能执行无法反馈给模型的调用。
- 上下文初始化现在位于 Run 的异常处理范围内；初始化失败会结束已启动的 Run，不留下运行中状态。
- 每个工具调用的进度回调有独立存活标记；成功或异常返回后永久失效，即使后续复用同一个 `call_id` 也不会重新生效。
- 这些入口是 runner 依赖的契约。模块内部实现可以独立演进；入口的参数、返回值或错误语义发生变化时，仍需要明确迁移调用方。
- 不新增 Application、审批等待、硬超时、持久化或异步执行；上下文的现有裁剪算法保持不变。

## 验证

保留直接回答、多次工具往返、策略拦截、流式、取消、各类时限、步骤上限和观察者失败隔离的现有测试；增加模块独立使用、Run 之间的上下文/用量/分片序号隔离、工具结果配对、旧进度回调失效及初始化失败终态的回归测试。假时钟改为注入事件发射与公共计时模块，并核对模型边界的具体耗时。
