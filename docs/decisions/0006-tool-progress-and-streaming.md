# 0006 工具进度回调与流式响应通道

## 背景（Context）

`ToolProgress` 与 `TokenChunk` 两个事件此前没有发射方：执行器契约是同步的三参数 `execute(call, context)`，没有上报进度的入口；MiMo 适配器只有一次性请求，`ModelProvider.generate(..., on_chunk=...)` 虽然被运行器传入，但适配器直接忽略它。

两者都需要在不破坏现有调用方式的前提下增加通道：现有执行器实现、测试和 `MimoProvider` 的一次性请求行为都必须继续可用。

## 决策（Decision）

- `ToolExecutor.execute` 增加可选参数 `on_progress: ProgressCallback | None = None`，回调只接受 `ProgressReport`（已完成计数、总数、阶段说明）。执行器按需多次调用；忽略它不产生任何事件。
- 运行器为每次工具调用创建回调，把上报转换为 `ToolProgress` 事件；调用结束后回调立即失效，延迟上报被忽略。
- 没有事件接收端时不传入回调（`on_progress=None`），执行器可以看到“本次运行没有观察者”。
- `MimoProvider.generate` 收到 `on_chunk` 时改用流式请求：`stream=True` 加 `stream_options={"include_usage": True}`，逐段回调文本增量，并在流结束时返回同样的 `ModelResult`。未提供回调时保持一次性请求。
- 流式工具调用按 `index` 累积：调用标识与名称取首次出现的值，参数按段拼接；个别提供方重复下发同一段时跳过重复内容。
- 不实现“先流式返回文本再补发工具调用”之类的增量结果契约：`ModelProvider.generate` 仍然一次性返回完整 `ModelResult`，`TokenChunk` 只是过程中的通知。

## 理由（Reason）

- 可选参数让契约扩展保持向后兼容：不理解进度的执行器不必修改，一次性提供方不必实现流式。
- 进度用数据对象而不是裸字符串，避免执行器把工具参数或结果内容塞进事件。
- 让“有没有观察者”由运行器决定，执行器可以跳过昂贵的进度计算。

## 备选方案（Alternative）

- 在 `ToolContext` 上挂进度回调：`ToolContext` 是冻结的数据对象，混入回调会让它与运行状态耦合。
- 增加独立的 `ProgressReporter` 服务：能力更强，但当前只有一个消费者，属于提前抽象。
- 为流式定义新的 `ModelProvider` 方法：接口更清晰，但会让一次性提供方也必须实现或适配两套入口。
- 在适配器内部直接发事件：会让 Infrastructure 依赖事件上下文与序列号规则，违反“事件由运行器在边界发出”的既有设计。

## 影响（Consequence）

- `ToolExecutor.execute` 的签名扩展为三个参数；已有实现需要接受或忽略第三个参数（抽象方法不强制子类声明它，但 `ABC` 的实例化检查按签名进行）。
- `ModelProvider.generate` 的 `on_chunk` 由“说明性契约”变为 MiMo 适配器的真实行为；测试覆盖文本分片、工具调用分片拼装与两轮流式工具往返。
- 流式请求会额外产生 `TokenChunk` 事件，事件数量与提供方分片数量一致；不传 `events` 时不产生任何事件，也不传入回调。
- `tools` 等调用方参数保持原样传递；`on_chunk` 不会被转发给模型服务。
