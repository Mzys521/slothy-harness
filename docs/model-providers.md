# 桌面模型提供商与模型切换

在设置页的「模型提供商」选择 DeepSeek、Qwen、MiMo 或 GLM，填写 API Key 后点击「保存并使用」。默认服务地址和文本模型已经预置，无需修改环境变量或重启。输入区的模型菜单可切换已配置提供商的模型；slothy chat 与 sloty coding 共用当前模型选择。

模型菜单中的变化只影响新任务。每个新任务保存 `{provider_id, endpoint_id, model}`，执行、审批恢复和已保存快照查询使用原绑定。API Key 轮换时，同一个提供商及服务区域的旧任务使用更新后的凭据；移除密钥后，依赖它的任务返回 `model_not_configured`，不会自动改用其他提供商执行。

## 官方预设

| 提供商 | 默认模型 | 默认接口 | 模型选择 |
| --- | --- | --- | --- |
| DeepSeek | deepseek-flash | https://api.deepseek.com | Flash / V4 Pro，可刷新模型列表 |
| Qwen | qwen-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 | Plus / Flash / Max / Coder，可刷新模型列表 |
| MiMo | mimo-v2.5-pro | https://api.xiaomimimo.com/v1 | V2.5 Pro / V2.5，可添加文本模型 ID |
| GLM | glm-5 | https://open.bigmodel.cn/api/paas/v4 | GLM-5 / GLM-4.7 / GLM-4.5-Air，可添加文本模型 ID |

Qwen 可另选新加坡或美国区域，各区域凭据独立保存。默认使用百炼兼容接口；GLM 默认使用开放平台的标准 API Key。当前未预置供应商专用 Coding Plan 地址。所有提供商均可选择「添加其他模型 ID」输入账号可用的文本模型；添加并保存后会进入快捷菜单。选择和保存设置不隐式调用远程服务。

DeepSeek / Qwen 的「刷新模型列表」通过所选区域的已保存凭据请求一次官方 models 接口，筛掉 embedding、rerank、音视频等模型；不自动遍历分页。刷新失败时保留原列表。MiMo / GLM 当前使用预置列表和手动添加。「测试连接」仅在用户点击后请求所选模型，输出限制为 8 tokens，不包含用户任务、历史、记忆或工具。界面区分已配置与实际连接测试成功；测试失败不会伪造成功状态。

默认预设参考以下官方文档，后续供应商变更可通过刷新或手动 ID 选择适配：

- [DeepSeek 模型与接口](https://api-docs.deepseek.com/quick_start/pricing/)、[思考模式与工具调用](https://api-docs.deepseek.com/guides/thinking_mode/)。新预设使用当前文档中的模型 ID。
- [阿里云 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[文本模型列表](https://help.aliyun.com/zh/model-studio/text-generation-model)。传统兼容接口继续可用，因此普通 API Key 无需额外配置 Workspace ID。
- [MiMo 文本接口与思考模式](https://platform.xiaomimimo.com/docs/en-US/usage-guide/passing-back-reasoning_content)。
- [智谱 GLM-5 接口](https://docs.bigmodel.cn/cn/guide/models/text/glm-5)。

## 密钥与执行边界

- Windows 使用当前 Windows 用户的 DPAPI 加密，密文保存在运行数据目录的 `model-credentials.dpapi`；正常默认目录为 Git 忽略的 `.slothy/desktop/`。复制到其他机器或 Windows 用户后不能直接解密。
- 其他平台只在宿主进程内保留凭据，前端明确提示重启后需要重新输入；不会降级写入明文文件。损坏的凭据文件不会被静默覆盖。
- 普通 SQLite 配置、任务目录、快照、事件、已完成历史及 API 响应只保存配置标识和 `configured` 状态，没有 API Key 或部分密钥。页面仅暂时持有用户正在输入的值，完成保存/操作、切换提供商或区域时清空，不写入 localStorage/sessionStorage。
- 凭据由 Infrastructure 在每次模型调用时按用户、提供商、区域查找，Core 的 `ModelProvider.api_key` 始终为 `None`。SDK 客户端在请求完成或失败后关闭。固定官方 HTTPS 地址禁止携带密钥自动跟随重定向，页面不能提交任意 Base URL。
- SDK 自动重试关闭；429、服务端错误与连接失败进入既有有限 Runtime RetryPolicy。鉴权失败、模型不可用、响应不合法转为稳定错误码，API 不回传供应商异常正文或请求头。
- 当前四家文本适配明确关闭深度思考：Core 不维护厂商特有的 reasoning_content，避免多轮工具请求缺少必需的思考回传字段。前端不显示内部推理。

原有环境配置的 DashScope / MiMo 用于兼容旧任务及尚未选择前端提供商的默认路径。RAG embedding / rerank / 摘要继续使用既有环境配置；切换文本提供商不会改变检索通道或给模型新增权限。独立 CLI 的 `--live` 配置保持原行为。

## 结构与验收

`ModelSettings` / `ModelPicker` → `bridge.ts` → `WorkspaceAPI` → `ModelService`。`desktop.py` 注入预设、凭据、验证、SDK 适配和 Runtime 工厂，Application 不导入 SDK/文件系统，Core 不新增供应商依赖。模型配置接口只面向 UI，不注册为模型工具。决定见 [ADR 0018](decisions/0018-model-providers-and-secure-credentials.md)。

离线检查只使用假密钥：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests/unit -p test_model_credentials.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests/integration -p test_model_settings.py -v
npm --prefix frontend run build
# 独立临时宿主，浏览器验收无需真实 API Key 或外部请求
.\.venv\Scripts\python.exe -X utf8 tests/e2e/model_fixture.py
node tests/e2e/model_settings_ui.mjs --playwright-module <playwright模块路径> --browser <Chrome路径>
```

SDK MockTransport 仅替换外部 HTTP，Application/Core/SQLite、SDK JSON/SSE 解析和工具执行均真实运行。覆盖四家密钥单字段配置、流式与函数参数分片、13 的真实加法工具结果、模型/区域切换、密钥轮换/移除、错误脱敏、快照恢复与密钥不会进入数据存储。真实供应商账号可用性需在设置中通过「测试连接」确认。
