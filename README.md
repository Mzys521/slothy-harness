![Slothy 思洛 Logo](logos/word_logo_chinese_withe.png)

# Slothy / 思洛

![Version](https://img.shields.io/badge/version-0.3.0-60DD06)
![License](https://img.shields.io/badge/license-MIT-95611F)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)

**当前版本：0.3.0** · [更新日志](CHANGELOG.md)

Slothy 是一个基于 Python 的智能体 Harness 项目，目标是为桌面应用提供可控的模型调用、工具执行和运行状态管理。仓库同时包含 Vue 前端工作区。

## 当前进度

0.3.0 已包含可运行的 Python 智能体循环：模型提出工具调用，运行器将调用交给抽象执行器，执行结果再返回模型。Core 提供运行状态、取消、截止时间、工具定义与注册契约；Infrastructure 提供 MiMo 模型适配器和计算工具实现。计算工具包括加、减、乘、除和幂运算，均使用 `float` 参数。

Runtime 同时是可观察的：运行状态迁移和模型、工具调用边界会发出与提供方无关的事件（Run/Step 生命周期、模型请求与响应与流式分片、工具调用、进度、令牌用量与耗时指标），界面、日志和持久化通过事件接收端订阅，不需要侵入执行逻辑。详见[运行时事件](docs/runtime-events.md)。

Core 还提供上下文窗口与策略判定：`ContextWindow` 在令牌预算内裁剪最早的消息（保留系统提示与工具调用配对）并发出 `ContextCompressed`；`PolicyEngine` 在工具调用边界判定 `ALLOW`/`DENY`/`ASK`，被拦截的调用不进入执行器，改为向模型返回受控错误结果并发出 `PolicyTriggered`、`GuardrailBlocked`。MiMo 适配器支持流式响应，文本增量会转换为 `TokenChunk`。

Vue 桌面原型已接入真实 Application：居中任务输入、结构化任务状态、工具时间线、审批、记忆与运行预算。pywebview 桥接和回环网页预览复用同一服务，详见[桌面布局与启动](docs/desktop-ui.md)。调度、外部插件与产品安装包仍属后续范围。

侧栏顶部支持切换 slothy chat / sloty coding；Chat 隐藏项目环境，Coding 在侧栏展示可折叠项目与子任务。创建/编辑项目时添加源文件夹，详情支持路径、仓库、任务数量与置顶；设置页保存 Coding 权限和执行预算。Coding 支持目录浏览、UTF-8 文件读取、代码检索、带文件指纹的修改/写入，以及固定测试/构建检查。每次修改与检查分别审批，已有任务始终绑定原目录和权限；说明见 [Coding 工具设计](docs/decisions/0016-coding-agent-mode-and-controlled-tools.md)与[模式和项目设计](docs/decisions/0017-work-modes-and-project-workspaces.md)。

[Application 接口](docs/application-api.md) 已提供 `RuntimeAPI → RuntimeService → Core`：创建、执行、查询、取消、暂停、审批、恢复及工具目录均为独立操作，返回 JSON DTO；支持所属用户隔离和事件 DTO 推送。批准工具后须单独恢复，API 不暴露原始快照或 Core 实体。`main.py` 仅为[独立演示组装根](docs/main-demo.md)，产品使用 Application。

[MCP/RAG 后续计划](docs/plans/mcp-rag-plan.md) 记录分层、实施顺序、重放安全与验收门槛。受控 RAG 检索和结果分页工具已随分层 Context 实现；MCP、自动来源导入与 manifest 仍属于后续计划。

`AgentRunner` 提供固定的运行入口，由 `RunExecution` 编排 Run/Step 生命周期与恢复游标：消息经 `context.conversation.add` 更新，模型经 `ModelSession.model_call` 请求，工具经 `ToolSession.tool_call` 执行；策略与事件转换封装在所属模块。原有调用方式保持兼容，详见 [模块入口设计](docs/decisions/0007-runner-module-entrypoints.md)。

正式 [Context System](docs/context-system.md) 提供四层 `LayeredContext`：可信系统规则、工作记忆、结构化任务状态和按需检索的长期记忆。Runner 只通过 `get_windowed_messages()` 读取受预算约束的 XML 窗口；长工具结果先存入 SQLite，使用引用与分页查询。向量/BM25/实体通道融合时间衰减并支持重排回退，滚动摘要只能使用 chat 模型。旧 `InMemoryContext`、`ContextWindow` 和策略类由兼容适配器保留，见[配置](docs/context-configuration.md)与[迁移说明](docs/context-migration.md)。默认离线演示验证 8k 输入预算。

[Runtime 快照与恢复](docs/runtime-recovery.md) 支持版本化 JSON、SQLite 持久存储及 `runner.resume()`。已完成工具直接复用结果；普通幂等工具可重试，非幂等工具通过稳定键校验执行凭据。不可校验的尝试进入 `WAITING_APPROVAL`，宿主取得用户决定后才继续；桌面原型提供批准、拒绝与独立恢复操作。`scripts/demo_runtime_recovery.py` 展示重启后凭据复用与未知结果阻塞。

## 架构

正式 [Policy System](docs/policy-system.md) 将步数、协作式超时、异常处置、重试和无进展检测移入可注入策略。`DefaultPolicy(5)` 与 `TimeoutPolicy(DefaultPolicy(20), timeout_seconds=30)` 使用同一 Runner，可组合 `RetryPolicy` 和 `SafetyPolicy`。`scripts/demo_policy_system.py` 可无网络验证这些行为。同步阻塞调用仍需底层支持超时，尚无进程级强制中断。

依赖方向为 `Vue → Presentation → Application → Core`。Infrastructure 实现 Core 定义的接口，Core 保持纯 Python，不依赖具体模型 SDK、桌面框架或操作系统实现。详见 [架构说明](docs/architecture.md)和[开发指南](docs/Slothy-Development-Guide.md)。

| 目录 | 职责 |
| --- | --- |
| `src/slothy/core/runtime/` | 固定运行入口、恢复游标、快照契约、Run/Step 状态及取消和截止时间 |
| `src/slothy/core/events/` | 运行时事件契约、按类型分发的事件总线与事件时间线 |
| `src/slothy/core/context/` | 四层上下文、预算降级、XML 组装、检索契约与旧接口适配器 |
| `src/slothy/core/policy/` | 运行终止、时限、重试、安全规则和无进展策略 |
| `src/slothy/core/model/` | 模型提供方接口及模型响应类型 |
| `src/slothy/core/tools/` | 工具定义、注册表、执行契约、重放日志、幂等校验和审批请求 |
| `src/slothy/core/agent/` | 预留智能体相关抽象；当前执行循环由 runtime 管理 |
| `src/slothy/infrastructure/app_tools/` | 计算工具、具体执行器及 SQLite 幂等凭据适配器 |
| `src/slothy/infrastructure/persistence/` | SQLite Runtime 快照存储 |
| `src/slothy/infrastructure/context/` | SQLite/FTS5、混合检索、DashScope 适配器与受控记忆工具 |
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

演示默认组装新分层 Context、脚本模型、计算与记忆工具，通过 Application API 验证 XML Prompt、8k 历史降级、策略重试、事件观察及暂停恢复。真实 MiMo 调用仍需显式 `--live`，并先在本地配置 `MIMO_API_KEY`、`MIMO_BASE_URL` 和 `MIMO_MODEL`：

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

生产 Context 把长工具结果外化到 SQLite，使用结构化 TaskState、滑动窗口/滚动摘要和带预算的长期记忆。`search_memory` 支持向量、BM25、实体与时间衰减，重排失败回退；`get_result` 按宿主范围分页读取结果。详情见 [Context 系统](docs/context-system.md)、[配置](docs/context-configuration.md) 和[迁移说明](docs/context-migration.md)。旧 Context 类与 RuntimeAPI 调用方式保留；Application 增加原子 `MemoryAPI.remember/search`。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --layered --context-db .slothy/context.sqlite3
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --legacy-context
```

DashScope 实际验证使用 `--layered --live`，文本模型需另配 `DASHSCOPE_CHAT_MODEL`；`DASHSCOPE_MODEL` 只用于 embedding。所有认证只从环境读取，未配置摘要服务时安全降级。`.env.example` 全部使用占位符；`scripts/sync_context_env.py` 保留本地值并同步键名，运行数据位于已忽略的 `.slothy/`。

桌面端先构建前端，再从仓库根目录启动：

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe -X utf8 -m slothy.desktop
# 浏览器预览：加 --browser，访问 http://127.0.0.1:8765
```

桌面在设置页配置 DeepSeek、Qwen、MiMo、GLM，填写 API Key 即可使用预置模型，并可在输入区切换已配置提供商的模型。Windows 通过 DPAPI 加密保存密钥，切换只影响新任务；详见 [模型提供商](docs/model-providers.md)。旧任务仍兼容环境配置。未配置模型时禁用发送，工作区与记忆服务仍可使用，不自动替换为演示模型。快速 / 进阶实际注入 5 轮 / 30 秒与 20 轮 / 120 秒 Policy。前端开发服务将 `/api` 代理到上述真实后端：

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
