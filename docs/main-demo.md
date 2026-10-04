# main 独立组装演示

`src/slothy/main.py` 是快速验证程序和演示组装根。正式接口位于 [Application](application-api.md)，产品代码不得导入 main。现有 `api/`、`services/`、`dto/` 以及 Core / Infrastructure 目录保持原结构。

## 离线运行

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --demo --strategy trim
```

默认使用明确标识的脚本模型和真实 CalculatorToolExecutor，不读取 `.env`，不访问网络。脚本模型只用于测试，不解析任意自然语言任务。

组装通过 `assemble_demo()` 注入：

| 组件 | 演示配置 |
| --- | --- |
| Context | 每个 Run 独立 InMemoryContext，8192 估算 token 预算 |
| 压缩 | 默认 SummaryStrategy + 确定性演示摘要器；`--strategy trim` 换成截断 |
| Policy | DefaultPolicy(20) + 总时限 30 秒 + SafetyPolicy 允许列表/无进展检测 + RetryPolicy(2) |
| 工具 | 真实计算工具声明与 CalculatorToolExecutor，受控执行且声明幂等 |
| Runtime | 内存 SnapshotStore；可显式指定 SQLite 路径 |
| Application | RuntimeService / RuntimeAPI，创建与执行分开 |
| Observation | 通过 API 订阅 DTO，打印工具、压缩、策略、用量、流式片段与耗时 |

演示制造一次模型临时故障，随后运行八轮加法，在第三轮工具返回后请求暂停，再通过 `resume_run` 恢复。正常完成九个模型步骤，工具结果缓存不会重做。历史约 39k 估算 token；每次请求不超过 8192。打印 `[verification]` 指标，并用退出码校验完成状态、历史规模和最大请求预算。模型用量也是替身报告值，不能用作真实计费。

演示摘要器仅展示注入与回退接入点，输出计数及继续计算的提示，不是完整的语义摘要器。实际摘要器由组装根注入，其费用、时限和输出质量需要实现方负责。live 默认采用截断。

```powershell
# 同一 Application / Runner，换策略参数验证步骤上限（预期失败退出码 1）
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --demo --max-steps 5

# 显式保存快照；目录与数据属于本地运行数据，不应提交
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --demo --snapshot-db .local/runtime.sqlite
```

时限为协作式检查及向底层传递剩余时限，不提供任意同步调用的进程硬中断。main 不提供通过猜测 Run ID 自动认领快照的 CLI，重启接管由可信宿主调用 Service 的登记操作。

## 实际模型与交互输入

仅在显式 `--live` 模式下加载本地环境并使用 MiMo。按既有本地配置设置 MIMO_API_KEY、MIMO_BASE_URL、MIMO_MODEL；无需在代码或演示输出中打印其值。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --live --input "计算 2 + 3 * 4"
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --live --interactive
```

交互模式输入 `/exit` 或 EOF 结束。每次输入创建独立 Run，当前不提供跨 Run 会话上下文。`--interactive` 必须搭配 `--live`；`--max-steps` 和 `--timeout` 接受有效的正值。

`run_calculation()` 保留既有演示调用方式与 RunnerResult 返回值；产品调用使用 RuntimeAPI 的 JSON DTO。ToolReporter 仍支持安全的工具回调；自动订阅调用结束后解除，传入普通 EventSink 时保留其事件，避免共享 EventBus 上积累重复打印。

验收：集成测试覆盖默认演示、两种压缩策略、步骤上限和实际计算执行器 + SQLite + 新 Service 恢复；不调用真实模型服务。
