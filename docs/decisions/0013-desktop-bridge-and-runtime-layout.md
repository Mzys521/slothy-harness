# ADR 0013：桌面桥接、真实运行布局与用户目录

状态：已实施。

## 背景

Vue 初始页无法展示已有同步 Runtime / Context / Policy / Memory API。目标是在品牌约束下形成可运行桌面布局，所有运行数据来自真实接口，并保持 main.py 的独立演示职责。

## 决策

1. 桌面采用 Vue + pywebview，复用官方 Logo 与 CSS 品牌变量。空状态居中，激活状态优先展示实际 TaskState、工具与审批、事件和预算。
2. 前端使用统一 bridge.request(method, payload)。原生桥接与回环 HTTP 都只调用 WorkspaceAPI 白名单，不暴露 Core、任意反射调用、SDK 或文件能力。
3. WorkspaceService 绑定宿主用户，路由既有 RuntimeAPI / MemoryAPI；项目、灵感和任务归属通过 Core 的 WorkspaceCatalog 存储协议注入。SQLite 实现归 Infrastructure；Presentation 无 Core 导入。
4. 原 Runtime API 保持兼容，仅新增 inspect_run 展示投影。它读取不可变快照与安全 Context 报告，导出显式任务状态、配置计数、用量与模型名称，不导出原始快照、历史和结果。
5. 执行仍为同步 API；HTTP/pywebview 的宿主线程驱动长调用，前端可以独立读取事件、暂停与取消。创建与执行、决定与恢复分别调用，不改变审批安全语义。
6. 浏览器和桌面使用游标轮询事件，避免首次桥接引入额外消息服务。切换任务丢弃过期响应，缓存淘汰给出提示，日志导出不冒充持久审计。
7. 快速/进阶选择宿主预置 Policy。所有生成都是已配置文本模型，未配置禁用发送、失败返回真实错误；禁止静默切为 DemoModel。
8. 预置标题属于 SQLite 灵感模板，不是伪造执行记录。缺失的调度、插件、附件与发布服务通过能力状态明确显示，不加入假执行逻辑。
9. HTTP 仅绑定回环、校验 Host/Origin/自定义请求头与大小，不开放 CORS。静态资源目录和类型受限；输入与输出只作转义文本。

## 替代方案与理由

静态数据原型无法验收真实 Runtime，因此不采用。独立复制 Runner 到桌面会破坏模块边界，因此复用 Application。暂不引入 WebSocket/SSE 服务与新的认证框架；当前游标接口足以完成最小桌面闭环。

## 影响

新增 desktop.py 产品组装根、Presentation 桥接和预览服务、Workspace API/Service、目录存储及 Vue 布局。Core 保持纯 Python。目录不是多用户认证；已创建但未执行的任务重启后可能没有快照。事件缓存与采样报告也不是持久审计。超时与取消仍协作式；产品打包、调度、插件和完整审计以后续任务实现。

验证与使用见 [桌面布局](../desktop-ui.md)，原接口约束见 [Application API](../application-api.md)。
