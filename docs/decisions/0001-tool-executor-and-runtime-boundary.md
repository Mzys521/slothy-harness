# 0001 工具执行器与运行时边界

## Context（背景）

计算工具已能通过注册表提供给模型，但 Agent 循环需要明确的执行器契约和可观察的 Run/Step 状态。项目架构要求 Core 不依赖具体工具及外部系统。

## Decision（决策）

- 在 `core/tools` 定义抽象 `ToolExecutor`；具体计算执行器保留在 `infrastructure/app_tools`。
- 在 `core/runtime` 定义 Run、Step、状态、取消及总截止时间，交由现有 `AgentRunner` 驱动状态迁移。
- 取消与截止时间在模型和工具调用边界检查。`RunnerResult` 携带本次 Run，供调用方查看步骤记录。

## Reason（理由）

这种分层让 Core 只依赖抽象能力，保持现有 Agent 循环和工具实现，并为后续 UI、事件与持久化提供明确的状态数据。

## Alternative（备选方案）

将执行器接口与运行状态都放在主入口或具体计算模块中，改动起初更少，但其他工具与调用方无法复用，并会模糊 Core 与 Infrastructure 的责任。

## Consequence（影响）

现有 `AgentRunner.run` 调用保持兼容；需要取消或截止时间的调用方可以传入 Run 对象。同步模型或工具调用进行中无法被强制终止，取消将在下一次边界检查时生效。
