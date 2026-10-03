# Slothy Development Guide（思洛开发指导文档）

> **Document Type（文档类型）：** Development Guide（开发指导文档）  
> **Language（语言）：** Chinese（中文）  
> **Version（版本）：** v1.0  
> **Status（状态）：** Draft（草案）  
> **Project（项目）：** Slothy（思洛）  
> **Scope（适用范围）：** Desktop Application（桌面应用）、Harness Core（智能体运行约束核心）、Frontend（前端）、Application Layer（应用层）、Infrastructure（基础设施层）

---

# 1. Document Purpose（文档目的）

本文件用于指导 Slothy（思洛）从 Project Initialization（项目初始化）进入正式 Development（开发）阶段。

当前 Technology Stack（技术栈）暂定为：

- pywebview（桌面网页容器）
- Vue 3（前端框架）
- Tailwind CSS（原子化样式框架）
- Python（编程语言）
- Git（版本控制系统）

当前 Architecture（架构）采用：

```text
Presentation Layer（表现层）
        ↓
Application Layer（应用层）
        ↓
Core Layer（核心层）

Infrastructure Layer（基础设施层）
        ↓
Core Abstraction（核心抽象）
```

本项目的首要目标不是快速堆积 Feature（功能），而是优先建立稳定的 Boundary（边界）、Contract（契约）、Dependency Direction（依赖方向）与 Execution Model（执行模型）。

---

# 2. Core Development Principle（核心开发原则）

Slothy（思洛）的 Development（开发）必须遵守以下原则。

## 2.1 Boundary First（边界优先）

在实现 Feature（功能）之前，应先明确：

- 当前逻辑属于哪一个 Layer（层）
- 当前 Module（模块）允许依赖哪些 Module（模块）
- 当前 Data Model（数据模型）是否属于 Core Model（核心模型）或 DTO（数据传输对象）
- 当前 Capability（能力）是否需要通过 Interface（接口）暴露
- 当前 External Dependency（外部依赖）是否应隔离到 Infrastructure Layer（基础设施层）

禁止为了快速实现 Feature（功能）而跨越已经建立的 Architecture Boundary（架构边界）。

---

## 2.2 Core Independence（核心独立）

Core Layer（核心层）必须保持 Framework Independent（框架无关）。

Core Layer（核心层）禁止直接依赖：

- pywebview（桌面网页容器）
- Vue 3（前端框架）
- Tailwind CSS（原子化样式框架）
- SQLite（嵌入式数据库）
- HTTP Framework（HTTP 框架）
- Windows API（Windows 应用程序接口）
- Concrete LLM SDK（具体大语言模型软件开发工具包）
- UI Component（用户界面组件）

Core Layer（核心层）只负责 Harness Core（智能体运行约束核心）的 Domain Logic（领域逻辑）。

---

## 2.3 Application as Gateway（应用层作为唯一入口）

Presentation Layer（表现层）不得直接调用 Core Layer（核心层）。

统一调用链必须保持为：

```text
Vue 3（前端框架）
        ↓
Bridge（桥接层）
        ↓
pywebview API（桌面网页容器接口）
        ↓
Application API（应用层接口）
        ↓
Application Service（应用服务）
        ↓
Core Layer（核心层）
```

Application Layer（应用层）是 Presentation Layer（表现层）进入 Harness Core（智能体运行约束核心）的唯一合法入口。

---

## 2.4 Infrastructure Isolation（基础设施隔离）

所有需要接触 External World（外部世界）的实现必须优先放入 Infrastructure Layer（基础设施层）。

包括：

- LLM Provider（大语言模型提供方）
- Database（数据库）
- File System（文件系统）
- Shell（命令行执行环境）
- Operating System API（操作系统应用程序接口）
- Logging Backend（日志后端）
- Network Client（网络客户端）

Core Layer（核心层）可以定义 Interface（接口），Infrastructure Layer（基础设施层）负责实现 Interface（接口）。

---

# 3. Architecture Responsibility（架构职责）

## 3.1 Presentation Layer（表现层）

Presentation Layer（表现层）包含两部分：

- Vue 3 Frontend（Vue 3 前端）
- pywebview Desktop Host（pywebview 桌面宿主）

主要职责：

- UI Rendering（用户界面渲染）
- User Interaction（用户交互）
- Window Lifecycle（窗口生命周期）
- Frontend State（前端状态）
- Bridge Invocation（桥接调用）
- Application Result Display（应用结果展示）

Presentation Layer（表现层）禁止承担：

- Agent Loop（智能体循环）
- Tool Execution（工具执行）
- Permission Decision（权限决策）
- Model Routing（模型路由）
- Persistence Logic（持久化逻辑）
- Harness Policy（智能体运行约束策略）

---

## 3.2 Application Layer（应用层）

Application Layer（应用层）负责组织 Use Case（用例）。

建议划分为：

```text
application/
├── api/
├── services/
└── dto/
```

### API（应用程序接口）

API（应用程序接口）负责提供 Presentation Layer（表现层）可调用的稳定入口。

未来可能包括：

- start_run（启动执行）
- cancel_run（取消执行）
- get_run（获取执行）
- list_tools（列出工具）
- approve_tool（批准工具）
- reject_tool（拒绝工具）
- get_settings（获取设置）
- update_settings（更新设置）

API（应用程序接口）不负责复杂 Domain Logic（领域逻辑）。

---

### Service（应用服务）

Service（应用服务）负责组织完整 Use Case（用例）。

例如：

```text
Receive Request（接收请求）
        ↓
Validate Input（校验输入）
        ↓
Convert DTO（转换数据传输对象）
        ↓
Call Core（调用核心层）
        ↓
Collect Result（收集结果）
        ↓
Convert Response DTO（转换响应数据传输对象）
        ↓
Return to Presentation（返回表现层）
```

---

### DTO（数据传输对象）

DTO（数据传输对象）用于隔离 Presentation Model（表现层模型）与 Core Model（核心模型）。

禁止 Vue 3（前端框架）直接依赖 Core Entity（核心实体）的内部结构。

必须形成：

```text
Core Model（核心模型）
        ↓
Application Mapping（应用层映射）
        ↓
DTO（数据传输对象）
        ↓
JSON（JavaScript 对象表示法）
        ↓
Vue 3（前端框架）
```

---

# 4. Core Layer（核心层）Design（设计）

Core Layer（核心层）建议保持以下 Domain Module（领域模块）：

```text
core/
├── agent/
├── model/
├── context/
├── tools/
├── runtime/
├── policy/
└── events/
```

---

## 4.1 Agent Module（智能体模块）

Agent Module（智能体模块）保留 Agent Lifecycle（智能体生命周期）相关抽象；当前 Agent Loop（智能体循环）的执行入口位于 Runtime Module（运行时模块）。

主要概念：

- Agent Identity（智能体身份）
- Agent Configuration（智能体配置）
- Future Agent Lifecycle Contract（未来的智能体生命周期契约）

Agent Module（智能体模块）不应直接负责：

- Concrete Tool（具体工具）
- Concrete Model SDK（具体模型软件开发工具包）
- Database Access（数据库访问）
- pywebview（桌面网页容器）
- UI State（用户界面状态）

---

## 4.2 Model Module（模型模块）

Model Module（模型模块）负责定义 Model Abstraction（模型抽象）。

核心目标：

```text
Core Layer（核心层）
不关心
OpenAI（模型服务）
DeepSeek（模型服务）
Qwen（模型服务）
Claude（模型服务）
```

Core Layer（核心层）只认识统一的 Model Provider（模型提供方接口）。

Concrete Provider（具体提供方）由 Infrastructure Layer（基础设施层）实现。

---

## 4.3 Context Module（上下文模块）

Context Module（上下文模块）负责：

- Message（消息）
- Conversation Context（会话上下文）
- Context Window（上下文窗口）
- Context Construction（上下文构建）
- Token Budget（令牌预算）
- Future Memory Injection（未来记忆注入）

Context Module（上下文模块）不得直接包含 UI Formatting（用户界面格式化）逻辑。

---

## 4.4 Tools Module（工具模块）

Tools Module（工具模块）负责定义 Harness Tool System（智能体运行约束工具系统）。

建议核心概念：

- Tool Definition（工具定义）
- Tool Registry（工具注册表）
- Tool Call（工具调用）
- Tool Runtime（工具运行时）
- Tool Result（工具结果）
- Tool Metadata（工具元数据）
- Tool Validation（工具校验）

Tool（工具）应被视为 Controlled Capability（受控能力），而不是普通 Python Function（Python 函数）。

---

## 4.5 Runtime Module（运行时模块）

Runtime Module（运行时模块）负责一次 Agent Run（智能体执行）的完整生命周期。

当前 `AgentRunner` 与 `RunnerResult` 位于 `core/runtime`，执行循环、步骤控制和终止条件由该模块管理。

建议核心模型：

- Run（执行）
- AgentRunner（智能体运行器）
- RunnerResult（运行结果）
- Step（步骤）
- Run Status（执行状态）
- Step Status（步骤状态）
- Deadline（截止时间）
- Cancellation（取消）
- Future Checkpoint（未来检查点）
- Future Resume（未来恢复）

建议状态至少考虑：

```text
IDLE（空闲）
RUNNING（运行中）
THINKING（思考中）
WAITING_TOOL（等待工具）
EXECUTING_TOOL（执行工具）
WAITING_APPROVAL（等待批准）
COMPLETED（已完成）
FAILED（失败）
CANCELLED（已取消）
```

---

## 4.6 Policy Module（策略模块）

Policy Module（策略模块）负责执行 Safety Boundary（安全边界）与 Permission Model（权限模型）。

未来可包括：

- Permission（权限）
- Policy Rule（策略规则）
- Capability（能力）
- Approval（批准）
- Denial（拒绝）
- Risk Level（风险等级）
- Workspace Boundary（工作区边界）

建议长期支持：

```text
ALLOW（允许）
DENY（拒绝）
ASK（询问）
ALLOW_ONCE（单次允许）
```

---

## 4.7 Events Module（事件模块）

Events Module（事件模块）应尽早建立。

建议未来存在：

- RunStarted（执行已开始）
- RunFinished（执行已结束）
- StepStarted（步骤已开始）
- StepFinished（步骤已结束）
- ModelStarted（模型调用已开始）
- ModelFinished（模型调用已结束）
- ToolRequested（工具已请求）
- ToolStarted（工具已开始）
- ToolFinished（工具已结束）
- ApprovalRequested（批准已请求）
- RunFailed（执行失败）

Event Bus（事件总线）用于降低 Runtime（运行时）、UI（用户界面）、Logging（日志记录）与 Persistence（持久化）之间的 Coupling（耦合）。

---

# 5. Infrastructure Layer（基础设施层）Design（设计）

建议初始目录：

```text
infrastructure/
├── llm/
├── persistence/
├── filesystem/
├── shell/
├── config/
└── logging/
```

---

## 5.1 LLM Infrastructure（大语言模型基础设施）

负责：

- API Client（应用程序接口客户端）
- Authentication（身份认证）
- Request Conversion（请求转换）
- Response Conversion（响应转换）
- Error Mapping（错误映射）
- Retry Adapter（重试适配）

禁止将 Provider Specific Logic（提供方特定逻辑）泄露到 Core Layer（核心层）。

---

## 5.2 Persistence Infrastructure（持久化基础设施）

负责未来的：

- SQLite（嵌入式数据库）
- Repository（仓储）
- Session Persistence（会话持久化）
- Run Persistence（执行持久化）
- Step Persistence（步骤持久化）
- Checkpoint Persistence（检查点持久化）

Core Layer（核心层）只依赖 Repository Interface（仓储接口），不依赖具体 Database（数据库）。

---

## 5.3 File System Infrastructure（文件系统基础设施）

所有 File Operation（文件操作）必须经过明确 Boundary（边界）。

未来建议统一受：

- Workspace Policy（工作区策略）
- Path Validation（路径校验）
- Permission Check（权限检查）
- Audit Log（审计日志）

控制。

---

## 5.4 Shell Infrastructure（命令行基础设施）

Shell（命令行执行环境）属于 High Risk Capability（高风险能力）。

禁止在早期阶段直接让 LLM（大语言模型）生成字符串后无条件传递给 Subprocess（子进程）。

未来必须引入：

```text
Command Request（命令请求）
        ↓
Validation（校验）
        ↓
Policy Check（策略检查）
        ↓
Permission Check（权限检查）
        ↓
Execution（执行）
        ↓
Result Capture（结果捕获）
```

---

# 6. Frontend Development（前端开发）Guideline（指导）

Frontend（前端）建议保持：

```text
frontend/src/
├── assets/
├── components/
├── views/
├── stores/
├── services/
├── types/
└── styles/
```

---

## 6.1 Components（组件）

Components（组件）只负责可复用 UI Component（用户界面组件）。

例如未来：

- RunStatus（执行状态）
- ToolCallCard（工具调用卡片）
- PermissionDialog（权限对话框）
- EventTimeline（事件时间线）
- StepItem（步骤条目）

Component（组件）不得直接包含 Application Business Logic（应用业务逻辑）。

---

## 6.2 Views（页面）

Views（页面）负责 Page Composition（页面组合）。

建议未来主要 Page（页面）：

- Overview（总览）
- Run Detail（执行详情）
- Tool Registry（工具注册表）
- Settings（设置）

如果以后增加 Observability（可观测性），可再扩展：

- Event Viewer（事件查看器）
- Trace Viewer（追踪查看器）

---

## 6.3 Stores（状态仓库）

Stores（状态仓库）负责 Frontend State（前端状态）。

例如：

- Current Run（当前执行）
- Run List（执行列表）
- Tool State（工具状态）
- Theme State（主题状态）
- User Settings（用户设置）

Stores（状态仓库）不得复制 Core State Machine（核心状态机）的业务逻辑。

---

## 6.4 Services（服务）

Frontend Service（前端服务）必须统一封装 Bridge（桥接层）。

Vue Component（Vue 组件）禁止在项目中到处直接访问：

```text
window.pywebview
```

统一路径应为：

```text
Vue Component（Vue 组件）
        ↓
Frontend Service（前端服务）
        ↓
Bridge（桥接层）
        ↓
pywebview API（桌面网页容器接口）
```

这样未来替换 Desktop Transport（桌面通信方式）时，可以降低 Migration Cost（迁移成本）。

---

# 7. Bridge（桥接层）Design（设计）

Bridge（桥接层）是 Vue 3（前端框架）与 Python（编程语言）之间的重要 Boundary（边界）。

必须遵守：

- Stable Contract（稳定契约）
- Explicit Input（显式输入）
- Explicit Output（显式输出）
- Serializable DTO（可序列化数据传输对象）
- Controlled Error（受控错误）
- No Core Object Leakage（禁止核心对象泄露）

不应直接把复杂 Python Object（Python 对象）暴露到 Vue 3（前端框架）。

建议所有 Bridge Response（桥接响应）都可以安全转换为 JSON（JavaScript 对象表示法）。

---

# 8. Development Phase（开发阶段）

建议 Slothy（思洛）第一轮 Development（开发）采用以下顺序。

---

## Phase 0（阶段 0）：Repository Baseline（仓库基线）

目标：

- Git（版本控制系统）完成初始化
- Directory Structure（目录结构）稳定
- Theme Specification（主题规范）落盘
- Development Guide（开发指导文档）落盘
- Python Environment（Python 环境）可用
- Vue 3 Workspace（Vue 3 工作区）可用

Acceptance Criteria（验收标准）：

- Repository（仓库）结构清晰
- `main` Branch（主分支）存在
- `dev` Branch（开发分支）按需要建立
- `.env` File（环境变量文件）不会进入 Git（版本控制系统）
- Frontend（前端）与 Python Backend（Python 后端）物理隔离

---

## Phase 1（阶段 1）：Core Skeleton（核心骨架）

只建立最小 Harness Kernel（智能体运行约束内核）。

目标：

```text
User Input（用户输入）
        ↓
Agent Runner（智能体运行器）
        ↓
Model Provider（模型提供方接口）
        ↓
Model Response（模型响应）
        ↓
Final Result（最终结果）
```

本阶段不要加入复杂 Tool System（工具系统）。

Acceptance Criteria（验收标准）：

- Core Layer（核心层）可以独立运行
- Core Layer（核心层）无 UI Dependency（用户界面依赖）
- Model Provider（模型提供方接口）完成抽象
- Agent Runner（智能体运行器）具备基本生命周期

---

## Phase 2（阶段 2）：Tool Runtime（工具运行时）

目标：

建立：

- Tool Definition（工具定义）
- Tool Registry（工具注册表）
- Tool Call（工具调用）
- Tool Runtime（工具运行时）
- Tool Result（工具结果）

初始 Tool（工具）数量应尽量少。

建议仅选择 Low Risk Tool（低风险工具）验证闭环。

Acceptance Criteria（验收标准）：

```text
LLM（大语言模型）
        ↓
Tool Call（工具调用）
        ↓
Tool Runtime（工具运行时）
        ↓
Tool Result（工具结果）
        ↓
LLM（大语言模型）
        ↓
Final Answer（最终回答）
```

完整闭环可运行。

---

## Phase 3（阶段 3）：Runtime State（运行时状态）

目标：

建立：

- Run（执行）
- Step（步骤）
- Status（状态）
- Cancellation（取消）
- Maximum Step（最大步骤）
- Deadline（截止时间）

Acceptance Criteria（验收标准）：

- 每次 Agent Run（智能体执行）拥有唯一 Identifier（标识符）
- Step（步骤）可以独立记录
- Runtime State（运行时状态）明确
- Cancel（取消）能够传播到执行链

---

## Phase 4（阶段 4）：Policy and Permission（策略与权限）

目标：

建立：

- Policy Engine（策略引擎）
- Permission Model（权限模型）
- Risk Classification（风险分类）
- User Approval（用户批准）

初始可以支持：

```text
ALLOW（允许）
DENY（拒绝）
ASK（询问）
ALLOW_ONCE（单次允许）
```

Acceptance Criteria（验收标准）：

- Tool（工具）不得绕过 Permission Check（权限检查）
- High Risk Tool（高风险工具）可阻断
- Ask Flow（询问流程）可进入 Waiting Approval（等待批准）状态

---

## Phase 5（阶段 5）：Event System（事件系统）

目标：

将主要 Runtime Transition（运行时状态转换）转换为 Event（事件）。

Acceptance Criteria（验收标准）：

- Run（执行）
- Step（步骤）
- Model（模型）
- Tool（工具）
- Approval（批准）

均存在对应 Event（事件）。

UI（用户界面）后续只需要订阅或接收 Event（事件），而不是侵入 Core Logic（核心逻辑）。

---

## Phase 6（阶段 6）：Application Layer（应用层）

目标：

建立稳定的 Application API（应用层接口）、Application Service（应用服务）和 DTO（数据传输对象）。

Acceptance Criteria（验收标准）：

- Presentation Layer（表现层）不直接引用 Core Layer（核心层）
- DTO（数据传输对象）与 Core Model（核心模型）分离
- Application Service（应用服务）完成主要 Use Case（用例）编排

---

## Phase 7（阶段 7）：pywebview Integration（pywebview 集成）

目标：

建立：

```text
Vue 3（前端框架）
        ↓
Bridge（桥接层）
        ↓
pywebview（桌面网页容器）
        ↓
Application Layer（应用层）
```

Acceptance Criteria（验收标准）：

- Desktop Window（桌面窗口）可启动
- Vue 3（前端框架）可加载
- Bridge（桥接层）可调用
- Application API（应用层接口）可返回 DTO（数据传输对象）
- Core Layer（核心层）仍然不知道 pywebview（桌面网页容器）的存在

---

## Phase 8（阶段 8）：Desktop UI（桌面用户界面）

目标：

优先实现 Runtime Visualization（运行时可视化），而不是 Chat UI（聊天界面）。

建议第一批 UI（用户界面）：

- Overview（总览）
- Run Detail（执行详情）
- Tool Registry（工具注册表）
- Settings（设置）
- Permission Dialog（权限对话框）

设计重点：

```text
Run（执行）
Step（步骤）
Tool（工具）
State（状态）
Permission（权限）
Event（事件）
```

而不是单纯：

```text
User Message（用户消息）
Assistant Message（助手消息）
```

---

## Phase 9（阶段 9）：Persistence（持久化）

目标：

支持：

- Conversation Persistence（会话持久化）
- Run Persistence（执行持久化）
- Step Persistence（步骤持久化）
- Tool Execution Persistence（工具执行持久化）

优先选择 SQLite（嵌入式数据库）作为本地 Desktop Persistence（桌面持久化）。

Acceptance Criteria（验收标准）：

- Application Restart（应用重启）后仍可读取历史 Run（执行）
- Core Layer（核心层）仍不依赖 SQLite（嵌入式数据库）

---

## Phase 10（阶段 10）：Observability（可观测性）

目标：

建立：

- Structured Logging（结构化日志）
- Trace（追踪）
- Duration（耗时）
- Token Usage（令牌使用量）
- Tool Execution Record（工具执行记录）
- Error Record（错误记录）

Acceptance Criteria（验收标准）：

任何一次 Run（执行）都能够回答：

```text
What happened?（发生了什么）
When did it happen?（什么时候发生）
Why did it fail?（为什么失败）
Which tool was called?（调用了哪个工具）
How long did it take?（耗时多久）
```

---

## Phase 11（阶段 11）：Desktop Capability（桌面能力）

在 Runtime（运行时）、Policy（策略）、Permission（权限）稳定之前，不建议过早开放高风险 Desktop Capability（桌面能力）。

建议顺序：

```text
Read File（读取文件）
        ↓
List Directory（列出目录）
        ↓
Write File（写入文件）
        ↓
Shell Read-only Command（只读命令）
        ↓
Shell Mutation Command（修改型命令）
        ↓
Process Control（进程控制）
        ↓
Desktop Automation（桌面自动化）
```

每增加一个 Capability（能力），必须同时考虑：

- Permission（权限）
- Risk Level（风险等级）
- Audit（审计）
- Timeout（超时）
- Cancellation（取消）
- Idempotency（幂等性）
- Recovery（恢复）

---

# 9. Git Workflow（Git 工作流）

推荐基础 Branch（分支）：

```text
main（主分支）
dev（开发分支）
```

Feature Branch（功能分支）建议：

```text
feature/<name>
fix/<name>
refactor/<name>
docs/<name>
chore/<name>
```

推荐 Flow（流程）：

```text
Feature Branch（功能分支）
        ↓
dev（开发分支）
        ↓
main（主分支）
```

---

## 9.1 Commit Convention（提交规范）

统一使用 Conventional Commits（约定式提交）。

推荐 Type（类型）：

```text
feat（新功能）
fix（缺陷修复）
refactor（重构）
docs（文档）
test（测试）
chore（工程维护）
build（构建）
ci（持续集成）
style（格式调整）
```

示例：

```text
feat: add tool registry
fix: handle cancelled run
refactor: separate runtime state
docs: update architecture guide
```

Commit Message（提交信息）必须描述真实变更，不应使用：

```text
update
change
fix bug
test
123
```

等低信息量描述。

---

# 10. Testing Strategy（测试策略）

测试结构：

```text
tests/
├── unit/
├── integration/
└── e2e/
```

---

## 10.1 Unit Test（单元测试）

Unit Test（单元测试）优先覆盖 Core Layer（核心层）。

重点：

- Agent Loop（智能体循环）
- Runtime State（运行时状态）
- Tool Registry（工具注册表）
- Policy Rule（策略规则）
- Permission Decision（权限决策）
- Event Dispatch（事件分发）

Unit Test（单元测试）不得依赖真实 Network（网络）或真实 External API（外部应用程序接口）。

---

## 10.2 Integration Test（集成测试）

Integration Test（集成测试）负责验证多个 Module（模块）组合后的行为。

例如：

```text
Application Service（应用服务）
+
Core Layer（核心层）
+
Fake Infrastructure（伪基础设施）
```

或：

```text
Tool Runtime（工具运行时）
+
File System Adapter（文件系统适配器）
```

---

## 10.3 E2E Test（端到端测试）

E2E Test（端到端测试）用于验证完整 Desktop Flow（桌面流程）。

例如：

```text
Open Application（打开应用）
        ↓
Create Run（创建执行）
        ↓
Receive Event（接收事件）
        ↓
Approve Tool（批准工具）
        ↓
Finish Run（完成执行）
```

E2E Test（端到端测试）应少而关键。

---

# 11. Error Handling（错误处理）

禁止跨 Layer（层）随意抛出无法解释的 Raw Exception（原始异常）。

推荐：

```text
Infrastructure Error（基础设施错误）
        ↓
Error Mapping（错误映射）
        ↓
Application Error（应用错误）
        ↓
DTO（数据传输对象）
        ↓
Presentation Error State（表现层错误状态）
```

Core Exception（核心异常）应该表达 Domain Meaning（领域含义），而不是具体 Provider Error（提供方错误）。

---

# 12. Configuration Management（配置管理）

Configuration（配置）必须与 Business Logic（业务逻辑）分离。

建议分类：

- Application Config（应用配置）
- Model Config（模型配置）
- Runtime Config（运行时配置）
- Tool Config（工具配置）
- Permission Config（权限配置）
- Logging Config（日志配置）

Secret（密钥）必须来自 Environment Variable（环境变量）或 Secure Storage（安全存储）。

禁止：

- Hard-coded API Key（硬编码应用程序接口密钥）
- Commit Secret（提交密钥）
- 将真实 `.env` File（环境变量文件）提交到 Git（版本控制系统）

---

# 13. Security Baseline（安全基线）

Slothy（思洛）属于 Agent Harness（智能体运行约束框架），Security（安全）应从第一阶段开始设计。

最低要求：

- External Input Validation（外部输入校验）
- Tool Argument Validation（工具参数校验）
- Workspace Boundary（工作区边界）
- Permission Check（权限检查）
- Audit Event（审计事件）
- Sensitive Data Masking（敏感数据脱敏）
- Safe Default（安全默认值）

核心原则：

> LLM（大语言模型）只能提出 Action Request（动作请求），不能直接获得 Operating System Capability（操作系统能力）。

正确链路：

```text
LLM（大语言模型）
        ↓
Action Request（动作请求）
        ↓
Validation（校验）
        ↓
Policy（策略）
        ↓
Permission（权限）
        ↓
Runtime（运行时）
        ↓
Infrastructure（基础设施）
```

---

# 14. UI Design（用户界面设计）Principle（原则）

Slothy（思洛）不是传统 Chat Application（聊天应用）。

UI（用户界面）的核心目标是展示 Agent Execution Flow（智能体执行流）。

优先级：

```text
Observability（可观测性）
        ↓
Control（控制）
        ↓
Intervention（干预）
        ↓
Replay（回放）
        ↓
Conversation（会话）
```

主要信息对象：

- Run（执行）
- Step（步骤）
- Tool Call（工具调用）
- Tool Result（工具结果）
- Permission Request（权限请求）
- Event（事件）
- Status（状态）
- Duration（耗时）

---

# 15. Theme Constraint（主题约束）

所有 UI（用户界面）必须遵守 Theme-Color-Constraints（主题配色约束）。

固定 Brand Color（品牌色）：

```text
Slothy Green（思洛绿色）   #60DD06
Slothy Cream（思洛奶油色） #FCEAC9
Slothy Brown（思洛棕色）   #95611F
```

核心原则：

> Green（绿色）负责 Action（行动）。  
> Cream（奶油色）负责 Warmth（温度）。  
> Brown（棕色）负责 Identity（品牌识别）。  
> Neutral（中性色）负责 Information（信息）。

禁止单个 Product（产品）自行重新定义 Primary Brand Color（主品牌色）。

---

# 16. Code Organization（代码组织）Rule（规则）

禁止建立无边界的公共目录，例如长期堆积：

```text
utils/
helpers/
common/
misc/
```

如果某个 Logic（逻辑）属于明确 Domain（领域），应优先放回对应 Domain Module（领域模块）。

Shared Module（共享模块）只允许保存真正 Cross-domain（跨领域）且稳定的基础定义。

---

# 17. Dependency Rule（依赖规则）

允许：

```text
Presentation Layer（表现层）
        ↓
Application Layer（应用层）

Application Layer（应用层）
        ↓
Core Layer（核心层）

Infrastructure Layer（基础设施层）
        ↓
Core Abstraction（核心抽象）
```

禁止：

```text
Core Layer（核心层）
        ↓
Presentation Layer（表现层）
```

禁止：

```text
Core Layer（核心层）
        ↓
Application Layer（应用层）
```

禁止：

```text
Core Layer（核心层）
        ↓
pywebview（桌面网页容器）
```

禁止：

```text
Vue 3（前端框架）
        ↓
Core Internal Model（核心内部模型）
```

---

# 18. Development Discipline（开发纪律）

每次增加 Feature（功能）之前，先回答：

1. 这个 Feature（功能）属于哪个 Layer（层）？
2. 是否需要新的 Interface（接口）？
3. 是否需要新的 DTO（数据传输对象）？
4. 是否会破坏现有 Dependency Direction（依赖方向）？
5. 是否涉及 Permission（权限）？
6. 是否涉及 Event（事件）？
7. 是否需要 Unit Test（单元测试）？
8. 是否需要 Integration Test（集成测试）？
9. 是否影响 Theme Constraint（主题约束）？
10. 是否需要 Architecture Decision Record（架构决策记录）？

如果第 4 项答案为“是”，应优先重新评估 Architecture（架构），而不是直接编码。

---

# 19. Definition of Done（完成定义）

一个 Feature（功能）只有满足以下条件才视为完成：

```text
□ Responsibility（职责）明确
□ Layer Boundary（层边界）正确
□ Dependency Direction（依赖方向）正确
□ Input Validation（输入校验）完成
□ Error Handling（错误处理）完成
□ Required Event（必要事件）完成
□ Unit Test（单元测试）完成
□ Integration Test（集成测试）按需要完成
□ Documentation（文档）同步更新
□ Theme Constraint（主题约束）未被破坏
□ No Secret（无密钥）进入 Repository（仓库）
□ Git Status（Git 状态）干净
```

---

# 20. Recommended Daily Workflow（日常开发流程）

建议每次 Development Session（开发会话）遵守：

```text
1. Pull Latest Code（拉取最新代码）
2. Create or Switch Branch（创建或切换分支）
3. Define Scope（定义范围）
4. Confirm Architecture Boundary（确认架构边界）
5. Implement Minimal Change（实现最小变更）
6. Run Unit Test（运行单元测试）
7. Run Integration Test（运行集成测试）
8. Check Formatting（检查格式）
9. Check Type（检查类型）
10. Review Git Diff（审查 Git 差异）
11. Update Documentation（更新文档）
12. Commit（提交）
```

不要在一个 Commit（提交）中混入大量无关变更。

---

# 21. Architecture Decision Record（架构决策记录）

以下情况建议创建 ADR（架构决策记录）：

- 更换 Desktop Framework（桌面框架）
- 更换 Persistence Strategy（持久化策略）
- 引入 Message Queue（消息队列）
- 引入 Plugin System（插件系统）
- 修改 Tool Runtime（工具运行时）模型
- 修改 Permission Model（权限模型）
- 修改 Core API（核心接口）
- 引入 Durable Execution（持久执行）
- 引入 Computer Use（计算机操作）
- 修改 Bridge Protocol（桥接协议）

ADR（架构决策记录）应至少包含：

```text
Context（背景）
Decision（决策）
Reason（理由）
Alternative（备选方案）
Consequence（影响）
```

---

# 22. Early-stage Restriction（早期阶段限制）

在 Core Runtime（核心运行时）稳定之前，不建议优先开发：

- Complex Animation（复杂动画）
- Plugin Marketplace（插件市场）
- Multi-agent System（多智能体系统）
- Computer Vision Automation（计算机视觉自动化）
- Cross-device Sync（跨设备同步）
- Cloud Account System（云端账户系统）
- Distributed Runtime（分布式运行时）

优先保证：

```text
Core Correctness（核心正确性）
        ↓
Tool Safety（工具安全）
        ↓
Runtime Stability（运行时稳定性）
        ↓
Application Boundary（应用边界）
        ↓
Desktop Integration（桌面集成）
        ↓
UI Experience（用户界面体验）
```

---

# 23. First Milestone（第一里程碑）

第一个正式 Milestone（里程碑）建议定义为：

> **Slothy MVP Runtime（思洛最小可行运行时）**

必须完成：

- Agent Runner（智能体运行器）
- Model Provider（模型提供方接口）
- Basic Context（基础上下文）
- Tool Registry（工具注册表）
- Tool Runtime（工具运行时）
- Run（执行）
- Step（步骤）
- Event Bus（事件总线）
- Application API（应用层接口）
- pywebview Bridge（pywebview 桥接层）
- Basic Desktop UI（基础桌面用户界面）

第一里程碑不要求：

- Full Memory System（完整记忆系统）
- RAG（检索增强生成）
- MCP（模型上下文协议）
- Multi-agent（多智能体）
- Computer Use（计算机操作）
- Cloud Sync（云同步）

---

# 24. Second Milestone（第二里程碑）

第二个 Milestone（里程碑）建议定义为：

> **Slothy Safe Desktop Harness（思洛安全桌面智能体运行约束框架）**

重点加入：

- Permission Model（权限模型）
- Policy Engine（策略引擎）
- Workspace Boundary（工作区边界）
- Persistence（持久化）
- Observability（可观测性）
- Approval Flow（批准流程）
- Safe File Tool（安全文件工具）
- Controlled Shell Tool（受控命令行工具）

---

# 25. Long-term Direction（长期方向）

当 Desktop Runtime（桌面运行时）稳定后，再考虑：

```text
Slothy Core（思洛核心）
        │
        ├── Desktop Runtime（桌面运行时）
        ├── Mobile Runtime（移动端运行时）
        ├── CLI Runtime（命令行运行时）
        └── Future Remote Runtime（未来远程运行时）
```

核心目标是让 Harness Core（智能体运行约束核心）尽可能保持 Platform Independent（平台无关）。

---

# 26. Final Development Rule（最终开发规则）

Slothy（思洛）的 Development（开发）不以“代码数量”衡量进度，而以以下内容衡量：

```text
Boundary Clarity（边界清晰度）
Architecture Stability（架构稳定性）
Runtime Correctness（运行时正确性）
Tool Safety（工具安全性）
Observability（可观测性）
Maintainability（可维护性）
Extensibility（可扩展性）
```

任何新增 Feature（功能）都不应以破坏这些基础能力为代价。

最终开发原则：

> **Presentation Layer（表现层）负责如何展示。**  
> **Application Layer（应用层）负责要做什么。**  
> **Core Layer（核心层）负责 Harness（智能体运行约束框架）如何工作。**  
> **Infrastructure Layer（基础设施层）负责如何接触外部世界。**

以及：

> **LLM（大语言模型）提出 Action（动作），Harness（智能体运行约束框架）决定是否允许，Runtime（运行时）负责执行，User（用户）保留最终控制权。**
