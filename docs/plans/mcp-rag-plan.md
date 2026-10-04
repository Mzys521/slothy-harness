# MCP 与 RAG 后续实施计划

- 日期：2026-10-04
- 状态：**规划，尚未实现**；本轮不新增 MCP/RAG 代码、依赖、空接口或数据库。
- 约束：[架构](../architecture.md)、[开发指南](../Slothy-Development-Guide.md)、[初始化指南](../Project-Initialization-Guide.md)、[工具注册](../tool-registration.md)。
- 前置：[Application API](../application-api.md)、[Context](../context-system.md)、[Policy](../policy-system.md)、[快照与重放安全](../runtime-recovery.md)。

## 1. 目标与范围

MCP 首期让 Slothy 作为客户端接入用户配置并信任的外部工具服务器，仍经过本地参数校验、策略、受控执行及结果处理。对外提供 Slothy MCP Server 另列后续阶段，不把内部审批/恢复接口直接暴露给模型客户端。

RAG 首期检索用户授权文档，在有限上下文内回答并提供可核对的来源。先完成导入、检索、权限和引用闭环，再实测向量化、混合检索和重排的收益。

两者都不让 Runner 识别 MCP SDK、向量数据库或文件路径。main 仅增加演示组装；真实操作继续由 Application 提供原子入口。正式代码阶段先以 ADR 固化契约与错误语义，再创建当前闭环需要的模块。

## 2. 可复用基础与缺口

| 已有基础 | 接入方式 | 后续缺口 |
| --- | --- | --- |
| ToolRegistry / ToolExecutor / ToolSession | 外部工具归一为本地声明，经执行器路由 | 远程 schema 校验、名称映射、传输与连接生命周期 |
| ReplaySafety / ToolJournal / 审批 | 复用重试、回执校验、未知结果阻塞 | 远端服务的真实幂等协议、可信风险声明 |
| Context / 8192 估算预算 | 检索结果经普通工具消息进入窗口 | 证据子预算、压缩后来源关联 |
| Policy / 事件 / 快照 | 共用限额、时限、进度、分类与恢复 | 连接/索引事件、来源与索引版本 |
| RuntimeAPI / RuntimeService | 宿主调用、所属用户审阅、DTO 推送 | 持久归属目录、认证、宿主调度、配置与凭据存储 |

当前本地工具回执不能证明远程副作用恰好执行一次，actor_id 也不是认证系统。远程能力上线前须补齐真实宿主身份绑定、凭据管理和持久归属目录，不能视作已经实现。

## 3. 依赖归属

下表为拟定位置，实施时按最小闭环创建，不提前新增空目录和空接口。

| 层 / 位置 | MCP 职责 | RAG 职责 |
| --- | --- | --- |
| Core：tools 与能力领域 | 中立目录/调用契约、schema/版本绑定、可信风险声明；复用工具模型 | SourceRef、Document、Chunk、Evidence、Citation；加载/嵌入/索引接口及导入/检索规则 |
| Infrastructure：mcp | SDK、stdio 子进程、HTTP、认证、协议协商、关闭连接与错误映射 | 后续 MCP Resource → DocumentLoader 适配 |
| Infrastructure：retrieval / persistence | Core 配置仓储实现 | 受控文件读取、解析库、嵌入提供方、关键词/向量索引、事务与 manifest |
| Application：api / services / dto | 连接配置、发现、启用/禁用、目录 DTO | 来源登记、导入作业、检索、结果与引用 DTO |
| Presentation | 配置/认证跳转、审批展示、事件转发 | 来源选择与授权、进度、引用定位 |
| main / 演示组装根 | 注入传输与执行器，用假服务器验证 | 注入加载器/检索器/嵌入器，用固定文档验证 |

Application 只依赖 Core；Infrastructure 实现 Core 接口。SDK、event loop、数据库客户端和 OS 句柄不进入 Core、DTO 或快照。Presentation 不直接操作 Core 实体。

## 4. MCP 方案

### 协议基线

本计划引用固定 **2025-11-25** 修订，便于复查，不声称它是当前最新版。M0 重新核对官方已发布修订与 SDK 支持范围，选择并锁定兼容版本，记录 ADR 与兼容测试；不同修订的传输和恢复规则不能混用。

该修订使用 tools/list 发现、tools/call 调用工具；工具注解的可信度取决于来源。本项目将注解作为参考，最终风险与重放声明由本地可信配置决定。[MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

第一闭环仅接入一个明确配置的 stdio 服务器与一个只读工具，处理分页、schema 和文本/结构化结果。HTTP、动态目录、资源、sampling/elicitation、后台 tasks 和对外 Server 分阶段评审，未支持能力明确拒绝。

### 调用链与操作草案

```text
宿主 → Application 连接/启用用例 → Core 目录接口 → Infrastructure MCP 客户端

模型 ToolCall → 参数/schema 校验 → 本地策略/权限 → ToolJournal 重放安全门
  → 受控 MCP ToolExecutor → MCP 客户端 → ToolResult → Context → 模型
```

拟定 Application 操作为 register_mcp_server、connect_mcp_server、discover_mcp_tools、enable_mcp_tool、disable_mcp_tool、disconnect_mcp_server 和查询。登记不启动进程，连接不自动启用全部工具，发现不执行。请求只提交配置 ID 与受限选项；程序、地址允许范围和凭据引用由宿主授权配置管理，不能接受模型提交任意命令或 URL。工具尝试审批复用 RuntimeAPI。

目录记录稳定 server_id、远端名、schema、定义摘要、执行版本与可信风险声明。当前本地名最多 64 个 ASCII 字母/数字/下划线/连字符，而远端名可能含点号或超长；生成稳定无冲突别名并保存映射，不能直接注册远端名。每个 Run 冻结工具版本；目录更新影响后续 Run，恢复遇到 schema/版本变化返回冲突。

远端结果先验证类型、schema、编码与字节上限，再归一为 ToolResult 并交 Context 管理 token。不自动读取返回 URI、下载媒体或将资源提升为系统指令。连接重建和工具重试分开，禁用 ToolJournal 之外的隐式写请求重发。

### 重放与审批

| 情况 | 声明与处置 | 验收 |
| --- | --- | --- |
| 可信确认无副作用且可重复读取 | IDEMPOTENT，有界重试且不重置时限 | 超时、重连、重复读取均沿用 Run 预算 |
| 有副作用且支持原子键校验及结果回执 | KEYED，发送稳定键与指纹，适配查询回执 | 同键同参数复用；不同参数拒绝；提交前后断线 |
| 无法验证副作用 / 无可信声明 | UNVERIFIABLE，每次尝试前等待具体用户决定 | 初次与未知结果后的再尝试均阻塞，批准只放行一次 |

JSON-RPC ID、PID、HTTP 会话 ID、网络重连及“只读”注解不是幂等凭据。键的传递方式属于服务能力契约，必须明确协商和验证，不假设 MCP 自动提供副作用 exactly-once。断线结果不明时先校验回执，不能校验则 WAITING_APPROVAL。

### 传输与凭据

所引用修订支持 stdio 与 Streamable HTTP；断开连接本身不等于取消请求，补读消息也不等于重做工具操作。[MCP Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

stdio 使用受控可执行程序、参数数组、工作目录和最小环境，stdout 专供协议，日志走 stderr。凭据在外层受控注入。HTTP 阶段采用所选修订的授权流程并绑定正确资源，令牌不进入 DTO、上下文和快照。[MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

地址与认证元数据须限制 SSRF，不透传未经验证的上游令牌。未来本地 HTTP Server 落实 Origin 校验、本地绑定及认证。[MCP 安全实践](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)

现有 Runner 同步，SDK 异步传输由 Infrastructure 管理适配及生命周期。慢操作由宿主工作线程驱动，取消/时限/关闭连接的实际保证须由适配器验证，不能把 event loop 交给 Runner 或 API。

## 5. RAG 方案

### 检索与生成分离

RAG 将检索得到的外部证据接入生成过程，具体实现按项目数据、权限和预算验证。[RAG 原始论文](https://arxiv.org/abs/2005.11401) 作为概念依据。关键词与稠密检索分别建立基线后再决定是否组合，不能假设向量化自动改善中文/代码检索。[DPR 论文](https://arxiv.org/abs/2004.04906)

```text
授权 SourceRef → 受控加载/解析 → 分块/稳定 ID → 准备索引版本 → 原子发布 manifest
所属用户查询 → ACL 过滤 → 检索 → 去重/可选重排 → 证据预算
  → 带来源的 ToolResult → Context → 回答 → 引用 DTO
```

首批来源为用户明确选择的本地纯文本/Markdown。API 接收已授权 SourceRef；Infrastructure 规范化路径、限定根目录并防止越界，模型不直接提供文件路径。PDF、Office、网页与 MCP Resource 加载器后续按实际需要加入。

### 数据与操作草案

| 模型 | 必要字段 |
| --- | --- |
| SourceRef | workspace、owner/scope、source_id、授权版本；实际路径/凭据留在适配层 |
| Document | document_id、来源 ID/版本、内容摘要、解析器版本、授权范围、有效状态 |
| Chunk | chunk_id、document_id、有限正文、章节/页码/偏移、分块配置版本、token 规模 |
| IndexRevision | index_id、文档/分块 manifest、嵌入模型版本/维度、状态；prepared 不可查询 |
| SearchRequest | 查询、宿主身份、授权范围、索引版本、top_k、证据预算；模型不能覆盖权限 |
| Evidence / Citation | chunk_id、来源版本、定位、摘要、分数、有限正文；展示地址经权限映射 |

Core 定义 DocumentLoader、EmbeddingProvider 与索引读写接口，具体解析、SDK 和存储位于 Infrastructure。Application 分开提供来源登记、导入作业创建、作业执行/取消、状态查询、知识检索、引用查询、来源移除；导入不偷偷启动 Run，检索不自动生成回答。

模型侧首期只开放受控只读 search_knowledge 工具，复用 ToolSession、Policy、Context。索引写入由 Application 用例协调；未来若开放写入工具，另定义审批和 KEYED 回执，不沿用只读声明。

### 预算、版本与持久化

待实测初值：分块目标 512 估算 token、重叠 64；top_k 默认 5、最大 10；每轮证据最多 2048 token，包含在当前 8192 总窗口中。这些是项目初值，不是论文承诺。查询量、文件大小、批次、嵌入费用和总耗时均设限额，按中文/代码评估调整。

去重键绑定来源授权域、内容摘要、解析/分块版本、嵌入模型版本和维度。先构建 prepared 版本，完整写入并核对 chunk 数后原子发布活动 manifest；故障保留旧版本。重试复用导入作业键，不能重复 chunk 或发布半成品。修改/删除生成新版本；已有 Run 引用仍指向当时版本，或明确显示失效。

先保证文档/授权/manifest 一致性，再按 R2 实测选向量存储，不提前安装依赖。嵌入模型或维度变化触发重建，不混查不兼容索引。正文、向量、缓存和副本的删除/保留规则同步，不能只删除 UI 列表而仍可检索内容。

### 权限、引用、压缩与恢复

检索前按宿主身份过滤候选，读取证据与展示引用前再次检查授权。越权文档不能进入模型窗口，也不能泄露标题/片段/分数。缓存按身份、权限版本、索引版本和查询分区。

文档和检索结果均为不可信数据，不能改变系统指令、工具允许列表或审批身份。提示词中的数据边界不是安全保证；本地权限与受控执行才是实际约束。

有限 ToolResult 保存来源标识和证据摘要；压缩须保留可核对的引用关联，不能以摘要冒充原始证据。回答引用须匹配本次授权证据，未知 ID、不可访问证据或证据不足时明确说明，不能编造来源。

恢复已完成检索优先复用快照里的有限证据，绑定索引版本和内容摘要，不能静默替换旧引用。纯读取可重复不意味着内容永远相同。导入断点、索引发布/删除需独立事务和幂等语义，不能直接套用模型 Run 游标。

## 6. 实施顺序与验收

| 阶段 | 前置 | 交付 | 进入下一阶段的门槛 |
| --- | --- | --- | --- |
| M0 / R0 契约准备 | 本轮 Application | 认证/归属/配置仓储方案；MCP 版本/SDK ADR；RAG 数据/索引/引用 ADR | 依赖方向、状态、错误与保留规则可审阅，不加入无消费方空接口 |
| M1 MCP 只读闭环 | M0 | 一个受控 stdio 服务器；分页/schema/别名；一个只读工具 | 假服务器验证启动/关闭、畸形响应、结果上限、策略拒绝与超时；Runner 无 SDK 依赖 |
| M2 MCP 远程/写入 | M1 + 真实认证/凭据 | HTTP、凭据绑定、KEYED 回执与 UNVERIFIABLE 审批 | 断线/回执丢失/键冲突不静默重做；拒绝和取消不执行；密钥不进事件/快照 |
| R1 文档/关键词基线 | R0 | 授权文本导入、稳定分块、manifest、关键词检索与引用 | 导入不重复；中断不发布半索引；越权召回为零；引用可定位 |
| R2 检索生成闭环 | R1 | 可替换嵌入/索引；稠密/混合比较；search_knowledge；预算和恢复 | 固定数据集 Recall@k / MRR、引用正确性、证据不足处理、中文/代码、8k 预算与恢复复用 |
| M3 / R3 联合验证 | M2、R2 按产品需要 | 授权 MCP Resource 导入、领域观察、产品桥接 | 远端来源仍经授权加载器；注入数据不能越权工具；断线和恢复可重现 |
| 可选 Slothy MCP Server | 接口/权限稳定 | 独立协议入站适配、最小工具目录 | 不直接导出审批；客户端认证、归属和控制边界独立验收 |

M1 和 R1 在各自契约稳定后可独立推进；联合资源导入等待两边权限与版本验收。MCP 工具接入不以 RAG 为前提，本地 RAG 也不依赖 MCP。

## 7. 验证与观测计划

Core/Application 单元测试使用假客户端、加载器、嵌入器、内存索引和假时钟，不访问真实外部 API。跨层集成用临时目录与本地假服务器，显式启动/回收子进程并覆盖 Windows 行为。真实服务仅用于独立 opt-in 演示，不进入默认测试。

MCP 矩阵涵盖分页/目录变化、名称冲突、版本不匹配、恶意 schema/结果、返回 URI、超时/取消、未知副作用、回执复用、旧审批和观察失败。RAG 矩阵涵盖中英/代码/空文档、分块、重复导入、故障发布、删除授权、越权召回、重建、引用虚构、压缩和恢复时来源变化。

事件只含受控标识、数量、耗时、错误分类、索引版本和预算。查询原文、正文、参数、令牌和原始远端异常不写普通事件。新领域事件须同时补契约、消费方、Core 分类表、Application 显式字段表和测试。

使用固定 gold 集与基线记录召回/排序、引用正确率、证据不足时行为、延迟和费用；发布门槛在 R0 确认。检索质量与生成质量分开评价，不能用“看起来回答正确”替代权限和引用验证。

## 8. 后续决策项

对应阶段再确定：正式协议/SDK 版本、传输并发模型、首批可信服务器及写入校验协议；语料规模、中文/代码评估集、嵌入是否允许外发、索引存储与保留期限；宿主认证、持久归属目录和调度实现。未决项不妨碍当前本地演示和已实现 Application 接口使用。
