![Slothy 思洛 Logo](logos/word_logo_chinese_withe.png)

# Slothy / 思洛

![Version](https://img.shields.io/badge/version-0.2.0-60DD06)
![License](https://img.shields.io/badge/license-MIT-95611F)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)

**当前版本：0.2.0** · [更新日志](CHANGELOG.md)

Slothy 是一个基于 Python 的智能体 Harness 项目，目标是为桌面应用提供可控的模型调用、工具执行和运行状态管理。仓库同时包含 Vue 前端工作区。

## 当前进度

0.2.0 已包含可运行的 Python 智能体循环：模型提出工具调用，运行器将调用交给抽象执行器，执行结果再返回模型。Core 提供运行状态、取消、截止时间、工具定义与注册契约；Infrastructure 提供 MiMo 模型适配器和计算工具实现。计算工具包括加、减、乘、除和幂运算，均使用 `float` 参数。

Runtime 同时是可观察的：运行状态迁移和模型、工具调用边界会发出与提供方无关的事件（Run/Step 生命周期、模型请求与响应与流式分片、工具调用、进度、令牌用量与耗时指标），界面、日志和持久化通过事件接收端订阅，不需要侵入执行逻辑。详见[运行时事件](docs/runtime-events.md)。

Core 还提供上下文窗口与策略判定：`ContextWindow` 在令牌预算内裁剪最早的消息（保留系统提示与工具调用配对）并发出 `ContextCompressed`；`PolicyEngine` 在工具调用边界判定 `ALLOW`/`DENY`/`ASK`，被拦截的调用不进入执行器，改为向模型返回受控错误结果并发出 `PolicyTriggered`、`GuardrailBlocked`。MiMo 适配器支持流式响应，文本增量会转换为 `TokenChunk`。

Vue 前端工作区可单独开发；桌面宿主、前端桥接层和产品界面仍在后续开发范围内。

[Application 接口](docs/application-api.md) 已提供 `RuntimeAPI → RuntimeService → Core`：创建、执行、查询、取消、暂停、审批、恢复及工具目录均为独立操作，返回 JSON DTO；支持所属用户隔离和事件 DTO 推送。批准工具后须单独恢复，API 不暴露原始快照或 Core 实体。`main.py` 仅为[独立演示组装根](docs/main-demo.md)，产品使用 Application。

[MCP/RAG 后续计划](docs/plans/mcp-rag-plan.md) 已记录分层、契约草案、实施顺序、重放安全与验收门槛，目前不包含这些能力的代码。

`AgentRunner` 提供固定的运行入口，由 `RunExecution` 编排 Run/Step 生命周期与恢复游标：消息经 `context.conversation.add` 更新，模型经 `ModelSession.model_call` 请求，工具经 `ToolSession.tool_call` 执行；策略与事件转换封装在所属模块。原有调用方式保持兼容，详见 [模块入口设计](docs/decisions/0007-runner-module-entrypoints.md)。

正式 [Context System](docs/context-system.md) 提供 `Context` 接口与 `InMemoryContext`：完整历史和请求窗口隔离，Runner 只通过 `get_windowed_messages()` 读取上下文。默认 8192 估算 token 预算，支持整组工具往返裁剪、超长工具结果缩短和可注入摘要器的 `SummaryStrategy`；摘要故障自动回退到截断。`scripts/demo_context_system.py` 可无网络验证 17 步、超过 90k 历史规模的长任务。

[Runtime 快照与恢复](docs/runtime-recovery.md) 支持版本化 JSON、SQLite 持久存储及 `runner.resume()`。已完成工具直接复用结果；普通幂等工具可重试，非幂等工具通过稳定键校验执行凭据。不可校验的尝试进入 `WAITING_APPROVAL`，宿主取得用户决定后才继续；桌面审批界面尚未接入。`scripts/demo_runtime_recovery.py` 展示重启后凭据复用与未知结果阻塞。

## 架构

正式 [Policy System](docs/policy-system.md) 将步数、协作式超时、异常处置、重试和无进展检测移入可注入策略。`DefaultPolicy(5)` 与 `TimeoutPolicy(DefaultPolicy(20), timeout_seconds=30)` 使用同一 Runner，可组合 `RetryPolicy` 和 `SafetyPolicy`。`scripts/demo_policy_system.py` 可无网络验证这些行为。同步阻塞调用仍需底层支持超时，尚无进程级强制中断。

依赖方向为 `Vue → Presentation → Application → Core`。Infrastructure 实现 Core 定义的接口，Core 保持纯 Python，不依赖具体模型 SDK、桌面框架或操作系统实现。详见 [架构说明](docs/architecture.md)和[开发指南](docs/Slothy-Development-Guide.md)。

| 目录 | 职责 |
| --- | --- |
| `src/slothy/core/runtime/` | 固定运行入口、恢复游标、快照契约、Run/Step 状态及取消和截止时间 |
| `src/slothy/core/events/` | 运行时事件契约、按类型分发的事件总线与事件时间线 |
| `src/slothy/core/context/` | 对话消息角色、令牌估算与上下文窗口裁剪 |
| `src/slothy/core/policy/` | 运行终止、时限、重试、安全规则和无进展策略 |
| `src/slothy/core/model/` | 模型提供方接口及模型响应类型 |
| `src/slothy/core/tools/` | 工具定义、注册表、执行契约、重放日志、幂等校验和审批请求 |
| `src/slothy/core/agent/` | 预留智能体相关抽象；当前执行循环由 runtime 管理 |
| `src/slothy/infrastructure/app_tools/` | 计算工具、具体执行器及 SQLite 幂等凭据适配器 |
| `src/slothy/infrastructure/persistence/` | SQLite Runtime 快照存储 |
| `src/slothy/infrastructure/llm/` | 具体模型提供方适配器（含流式响应） |
| `src/slothy/application/` | 原子用例 API / Service / DTO，归属检查及事件推送 |
| `src/slothy/main.py` | Context / Policy / Observation / 快照与 Application 的独立演示组装 |
| `frontend/` | Vue 3、TypeScript、Vite 和 Tailwind CSS 工作区 |
| `tests/` | 单元测试与集成测试 |
| `docs/` | 架构、开发约束和设计决策 |
| `scripts/` | 本地演示脚本（`demo_governance.py` 展示策略、进度与压缩事件） |

## 本地运行

需要 Python 3.11+。在 PowerShell 中安装 Python 项目：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

默认演示无需模型密钥，不读取 `.env` 或访问网络：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --demo
```

演示使用脚本模型与真实计算执行器，通过 Application API 验证 8k 上下文压缩、策略重试、事件观察及暂停恢复。真实 MiMo 调用需显式 `--live`，并先在本地配置 `MIMO_API_KEY`、`MIMO_BASE_URL` 和 `MIMO_MODEL`：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --live --input "计算 2 + 3 * 4"
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --live --interactive
```

交互模式输入 `/exit` 结束。每次输入创建独立 Run，当前没有跨 Run 会话上下文。工具回调示例：

```text
[tool running] power
[tool run success] power
[tool running] divide
[tool run failed] divide
```

完整演示通过 `DemoObserver` 消费 Application 的事件 DTO。既有 `run_calculation()` / `ToolReporter` 保留演示兼容性，只打印工具名与执行状态；被拦截调用打印 `[tool blocked] <工具名>`，传 `watch_tools=False` 可静默。产品不依赖这些 main 函数。

`.env` 是本地配置，请勿提交密钥。更多环境说明见[开发文档](docs/development.md)。

前端工作区可独立启动；需要与已安装 Vite 版本兼容的 Node.js 和 npm：

```powershell
cd frontend
npm install
npm run dev
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_*.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_*.py -v
```

## 文档与许可

工具定义和注册方式见[工具注册文档](docs/tool-registration.md)，运行时事件见[事件文档](docs/runtime-events.md)，架构决策见 [docs/decisions](docs/decisions)，版本变更见[更新日志](CHANGELOG.md)。项目采用 [MIT 许可证](LICENSE)。
