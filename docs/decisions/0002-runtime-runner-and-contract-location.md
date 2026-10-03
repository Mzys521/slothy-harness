# 0002 将运行器及共享契约归入对应的 Core 模块

## 背景

初期实现把 `AgentRunner` 放在 `core/agent`，把运行结果和工具契约放在 `core/model`。这些位置与执行生命周期、模型边界和工具边界的职责不一致。

## 决定

- `AgentRunner` 和 `RunnerResult` 位于 `core/runtime`，与 Run/Step 状态共同组成一次执行的运行时契约。
- `ToolContext`、`ToolResult` 和 `ToolRegistry` 协议位于 `core/tools`；具体计算工具和执行器仍位于 `infrastructure/app_tools`。
- `core/model` 只保留模型提供方接口及模型响应类型；`core/agent` 保留未来智能体抽象的空间。
- 此次整理只移动模块并更新导入与包导出，不改变运行器、工具或模型的执行行为。

## 影响

调用方应从 `slothy.core.runtime` 导入 `AgentRunner`、`RunnerResult`，从 `slothy.core.tools` 导入工具契约。原模块路径不再提供这些类型。
