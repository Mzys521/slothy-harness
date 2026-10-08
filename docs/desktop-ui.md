# Slothy 桌面布局与真实接口

此界面采用 Vue 3、TypeScript、Tailwind CSS、主题变量与 pywebview。以 1440×900 为基准：304px 侧栏、居中工作区、24px 固定状态栏；手动折叠侧栏为 76px。空状态显示当前模式、输入与任务建议；激活状态以紧凑可展开记录显示模型、工具、重试、审批与输出，右侧 304px 详情栏展示实际 TaskState 与上下文预算。窄窗口将详情栏转换为可关闭面板，640px 以下采用 60px 导航栏，可展开覆盖侧栏以操作项目。提供的 `logos/logo_picture.png` 原样用作品牌图标。

## 前端重写与参考

旧前端源码与构建输出先移除，再以 DeepSeek Harness 的侧栏、居中工作区、输入区和工具披露模式重新编写。参考版本固定为 `5badb15009ae1756c3afe0ae0cef1faafc290ccc`；组件改写为 Vue，不引入上游 React、插件运行时或后端服务。[第三方声明](../frontend/THIRD_PARTY_NOTICES.md)保留来源与 MIT 许可；设计边界见 [ADR 0014](decisions/0014-harness-inspired-frontend.md)。

前端按 `components / views / stores / services / types / styles` 组织。所有宿主调用只经过 `services/bridge.ts`；状态仓库管理 UI 请求与事件投影，组件不承担执行或授权。默认浅色，设置支持深色和跟随系统；所有主题保留规定的品牌常量。外观偏好仅保存在浏览器本地，业务数据仍由 Application 保存。

Ctrl K / Cmd K 准备新任务，Ctrl P / Cmd P 搜索真实任务目录；Enter 发送，Shift Enter 换行，输入法组字不触发发送。后续输入创建另一 Run；Application 在任务完成并提交快照后保存对话历史，为新 Run 注入最近已完成提问，不把当前草稿、进行中输入或活动工具结果当作上一轮。该能力不等于完整跨 Run 会话，见 [ADR 0015](decisions/0015-completed-run-memory.md)。原生 HTML dialog 管理焦点、遮罩和 Esc；审批决定与继续执行始终分开。

## 运行

在仓库根目录构建前端，然后启动桌面窗口：

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe -X utf8 -m slothy.desktop
```

浏览器预览与桌面使用同一真实服务：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.desktop --browser
# 打开 http://127.0.0.1:8765
```

开发时先启动上述后端，再运行 `npm --prefix frontend run dev`，访问 `http://127.0.0.1:5173`。Vite 仅将 `/api` 转发到本地后端。入口 `main.py` 仍仅供既有独立演示；桌面产品组装在 `desktop.py`。

默认运行数据保存在已忽略的 `.slothy/desktop/`。`--data-dir` 可配置目录，`--frontend` 指向构建输出，`--port` 改变回环端口。Vite 代理端口需与后端保持一致。原型尚无安装包，需要从仓库根目录启动。

## 依赖与接口

```text
Vue → services/bridge.ts → DesktopBridge / 本地 HTTP
    → WorkspaceAPI → WorkspaceService → RuntimeAPI / MemoryAPI
    → RuntimeService / MemoryService → Core

desktop.py 注入真实模型、工具、Context、Policy、SQLite 与目录适配器
Infrastructure 实现 Core 契约，Presentation 不导入 Core 或 SDK
```

前端仅调用 JSON 方法白名单。新任务按钮、Ctrl K 与工具提示仅准备草稿；发送时先 `create_task`，再单独 `execute_run`。通用助手快速模式最多 5 轮 / 30 秒，进阶最多 20 轮 / 120 秒；Coding Agent 分别为 20 轮 / 300 秒与 60 轮 / 900 秒，均真实注入 Policy。审批先作决定，再由用户点击“继续执行”单独恢复，不隐式批准或重试。

| 方法 | 用途 |
| --- | --- |
| workspace | 实际用户、文本模型状态、能力、项目、任务与灵感目录 |
| create_project | 保存项目名称与通过宿主校验的源文件夹 |
| update_project | 编辑名称、源文件夹或置顶状态；旧任务保留原绑定 |
| inspect_project_directory | 验证本机完整路径，返回目录与可识别的公开仓库信息 |
| choose_project_directory | 原生文件夹选择；浏览器返回 available=false，取消返回空选择 |
| save_inspiration | 保存用户的提示模板；预置三个模板单独标识为灵感，不能冒充已执行历史 |
| model_settings / save_model_provider / select_model | 配置与切换文本模型，响应仅含无密钥配置 |
| test_model_connection / refresh_provider_models / remove_model_key | 独立短请求测试、刷新文本模型及删除所选区域凭据 |
| create_task | 关联项目、选择宿主模式、创建 IDLE Run；不调用模型 |
| inspect_run | 所属用户的 Run、TaskState、预算报告、模型名称与累计用量投影 |
| execute_run / interrupt_run / cancel_run / resume_run | 原 RuntimeAPI 原子控制入口 |
| get_approval / approve_tool / reject_tool | 带请求 ID 和快照版本的审批流程 |
| get_events | 真实事件游标分页；浏览器与桌面均定期补读，不模拟时间线 |
| list_tools | 按 agent_mode 返回真实注册目录与参数 schema |
| update_coding_settings | 保存修改权限、检查允许列表与检查时限；应用于新任务，兼容旧全局目录字段 |
| remember / search_memory | 独立 MemoryAPI 写入与检索 |

普通接口不暴露原始快照、上下文历史、工具处理函数、SDK、认证或原始结果；审批参数仅在所属用户审批接口中读取。TaskState 按实际投影显示结构化分组，并提供 JSON 展开；plan/completed_steps/todo_list 为空时也保持为空，不根据模型文字杜撰完成状态。

状态栏读当前 Context 的实测报告，包含 XML、原生 schema 与用户缓冲开销；System 段包含 tool_schemas，Working 段包含当前用户缓冲，Output 段明确表示预留。未开始运行或没有报告时显示“未采样”。模型 token 总数来自真实 usage，不从估算值推算账单。日志导出只包含 API 已提供的事件；旧事件超出缓存时显示提示。

## 模型和能力

设置页可配置 DeepSeek、Qwen、MiMo、GLM 的 API Key、服务区域和文本模型，输入区提供已配置模型的快捷菜单。密钥由 Windows DPAPI 加密保存，普通 API 不回传；新任务固定模型，切换不改变已有任务的运行和恢复。尚未选择前端提供商或旧任务可继续使用环境中的 DASHSCOPE_CHAT_MODEL / MIMO_MODEL；DASHSCOPE_MODEL 只用于向量。详见 [模型提供商](model-providers.md) 和 [ADR 0018](decisions/0018-model-providers-and-secure-credentials.md)。未配置文本模型时保留工作区与记忆操作，禁用发送并提示设置；任何模型调用失败都不会切换到演示模型。

侧栏顶部是唯一模式入口，显示名称为 slothy chat / sloty coding。Chat 注册 add、search_memory、get_result，并隐藏项目环境。Coding 侧栏展示项目文件夹与可折叠的子任务。创建/编辑弹窗添加源文件夹，桌面使用系统选择器，浏览器填写完整路径。详情菜单显示任务数、可识别仓库与本地路径，并支持置顶和编辑。输入框中已删除模式切换。执行预算与 Coding 权限在设置页调整。Coding 增加 list_files、read_file、search_code，以及按设置启用的 edit_file、write_file、run_checks。新任务绑定启动时的目录与配置，界面显示实际绑定路径，后续改设置不改变历史任务。模式、项目折叠和选中项目是浏览器本地偏好，两种模式的草稿分别保留；项目目录、置顶和 Coding 权限保存在宿主 SQLite。切换模式不取消后台任务。多项目目录与兼容策略见 [ADR 0017](decisions/0017-work-modes-and-project-workspaces.md)。修改和检查每次等待人工审批；检查仅有 Python 单元/集成测试、npm 构建/测试、Git 差异空白检查预设，没有任意终端。工具边界与限制见 [ADR 0016](decisions/0016-coding-agent-mode-and-controlled-tools.md)。任务建议只准备草稿。定时调度、外部插件安装、自动网页浏览、设计软件操作、附件读取和客户端下载服务尚不存在。

服务只监听 127.0.0.1，绑定固定本地用户，属于单用户原型而非网络登录服务。HTTP 校验 Host/Origin、JSON、长度和固定自定义请求头，不开放 CORS；静态资源限制目录与文件类型。模型输出与输入通过 Vue 文本插值显示，不使用 v-html。弹窗支持焦点约束、Esc 退出；控件、状态文字与 CSS 变量遵守[配色约束](Theme-Color-Constraints.md)。

## 恢复与限制

目录和快照分别存储；重启时只加载目录已知所属用户的快照，不执行。缺失/损坏快照显示不可用，绝不重新调用工具补造数据。创建后尚未执行的 IDLE 记录可能没有快照，重启后需另建任务；缓存事件不是持久审计。活动上下文报告重启后可能暂无采样，状态栏明确说明。

时间线基于真正的模型/工具/策略事件；失败后重试保留失败节点和次数，终态不假装等待。底层同步调用仍不能由 UI 强制杀死，暂停与取消保持 Runtime 的协作式保证。多用户认证、定时服务、插件安装、完整产品打包与持久事件审计留待后续独立开发。

## 验证

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_*.py
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_*.py
```

`tests/integration/test_project_workspace.py` 另覆盖多项目目录绑定、编辑与审批恢复、元数据、置顶、目录选择和租户隔离。`tests/integration/test_desktop.py` 覆盖真实项目/目录、模式、工具事件、预算投影、重启恢复、拒绝越权与 HTTP 来源边界。E2E 使用真实 HTTP/Application/SQLite，外部模型为明确的 test-chat。仅测试宿主为控制用例注入短暂等待，为 quick 模式的 add 注入不可验证重放声明，驱动真实审批与恢复；这些注入不进入生产组装：

```powershell
.\.venv\Scripts\python.exe tests/e2e/desktop_fixture.py
node tests/e2e/desktop_ui.mjs --playwright-module <playwright模块路径> --browser <Chrome或Edge路径>
```

截图写到 `.slothy/desktop-qa/`，不提交运行记录或测试数据库。E2E 不拦截前端网络、不伪造响应、不使用真实外部 API。桥接契约参考 [pywebview 官方文档](https://pywebview.flowrl.com/guide/interdomain.html)。

2026-10-05 前端重写验收：TypeScript/Vite 构建通过，223 项 Python 单元测试和 61 项集成测试通过。Chrome E2E 覆盖项目、灵感、记忆、重试记录、输入法、斜杠工具菜单、模式、真实用量、日志导出、主题保存、原生模态焦点、任务搜索、暂停/继续/取消、批准/拒绝与 1440×900、880×700、390×844 布局。已检查对应截图；取消使用中性状态提示，审批决定不会自动恢复。上游 MIT 声明随构建复制到 `dist/THIRD_PARTY_NOTICES.txt`。

2026-10-05 完成历史修复验收：230 项单元测试、71 项集成测试及 TypeScript/Vite 构建通过。Chrome E2E 增加先完成一轮、再追问“我刚刚问了什么？”的真实记忆链路，使用显式离线模型读取宿主注入的上一轮记录；已检查 `completed-memory-followup.png`。现有暂停、取消、审批、检索和窄屏用例继续通过；测试不调用外部模型服务。

2026-10-05 Coding 模式验收：239 项单元测试、77 项集成测试及 TypeScript/Vite 构建通过，无跳过用例。Windows 链接边界使用真实 junction 验证。Chrome E2E 完整覆盖目录未配置时禁用发送、无效/有效设置保存、工具与模式切换、真实文件修改、两次分别批准/恢复、检查完成、配置刷新保存和三种窗口尺寸。已检查 `coding-settings.png`、`coding-approval.png` 与 `coding-completed.png`；恢复后的历史审批不再显示等待恢复。测试模型明确注入，未调用真实外部 API。

2026-10-06 独立模式与项目验收：242 项单元测试、85 项集成测试、TypeScript/Vite 构建和 Chrome E2E 全部通过，无跳过。浏览器验证侧栏顶部模式、键盘菜单、独立草稿、项目创建/目录校验/详情/折叠/编辑/置顶、刷新保存、任务与工具隔离、模式切换期间的后台任务，以及延迟创建响应不覆盖新的模式和草稿。实际临时文件经历修改与检查的两次独立审批；完成记忆、暂停/继续/取消继续通过。已检查浅色、深色与 1440×900、880×700、390×844 截图，原生目录选择器通过窗口替身验证参数、取消、串行和异常恢复；浏览器实际验证路径回退。测试服务器与模型仅用于离线验收。
