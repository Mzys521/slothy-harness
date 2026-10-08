# Context System 迁移说明

## 删除与保留

旧 memory.py 的历史/活动窗口实现、window.py 的独立软裁剪算法及 strategies.py 的旧裁剪/摘要算法已删除。三个文件现在仅提供兼容入口；共享校验、缩减和提交逻辑位于 validation.py/reduction.py。返回记录位于 records.py，并从旧 window 模块重导出。

`Context`、`InMemoryContext`、`ContextWindow`、`TrimOldestStrategy`、`SummaryStrategy`、`TokenEstimator`、`HeuristicTokenEstimator`、`CompressionRecord`、`WindowBuild`、错误类、conversation.add/restore、AgentRunner.run/resume 的公开调用形式继续可用。没有将同步方法改成异步。Runner 文件没有加入 Context 的内部逻辑。

旧 `ContextWindow.build()` 仍返回软预算窗口，包括一条自身超限的最新消息。`get_windowed_messages()` 现在对这种结果抛出已有 `ContextBudgetExceededError`，避免真正发送超限请求。旧代码仅展示 build 结果时无需改动；依赖超限请求继续执行的调用需配置更大预算或迁移到分层 Context。

## 旧调用方

```python
from slothy.core.context import InMemoryContext, SummaryStrategy

context = InMemoryContext(token_budget=8192, strategy=SummaryStrategy(summarize))
context.add({"role": "user", "content": "任务"})
messages = context.get_windowed_messages()
```

上述格式与返回数据类型不变。兼容适配器保留旧历史与消息角色布局，不自动访问数据库或外部模型，也不把旧自定义摘要器升级成生成模型服务。

## 新产品组装

```python
from slothy.application.services import RuntimeService
from slothy.core.runtime import AgentRunner
from slothy.infrastructure.context.assembly import assemble_context_components

components = assemble_context_components(path=".slothy/context.sqlite3", remote=True)
registry.register_many(components.definitions)

def runner_factory():
    context = components.create_context(system_prompt="完成当前任务，遵守工具规则。")
    executor = components.create_executor(registry, existing_executor)
    return AgentRunner(chat_model, registry, executor, context=context,
                       policy=policy, snapshot_store=snapshot_store)

service = RuntimeService(runner_factory, registry, snapshot_store=snapshot_store)
```

这是宿主组装代码；Application 内部不导入具体组件。创建、执行、查询、审批和恢复仍使用原 RuntimeAPI。每个 Run 独立创建 Context/Runner；共享存储与定义，不共享活动上下文。每个 Run 的外部执行器也必须符合既有单驱动与权限约束。

### 返回内容

LayeredContext 的 get_windowed_messages 仍返回 `list[dict]`，但内容是一个可信 system 消息和一个 XML 数据 user 消息。工具往返作为 working_memory JSON 保存，模型原生 tools 参数仍可产生 Function Calling。不能继续假定请求最后一条一定是 tool；解析 XML 只供测试/演示，产品通常不需要解析 Prompt。

LayeredContext.get_history 返回活动原始对话及有界 observation；旧段落在 SQLite 归档链。工具结果包含 observation 的 Result_ID/status/digest。长结果原文需通过受控 get_result 分页读取。旧 InMemoryContext.get_history 仍维持旧完整历史语义。

## 快照迁移与幂等

- 旧 `in_memory` / `window` 快照继续由旧适配器恢复。存量在途 Run 先以原配置和依赖完成，再为新 Run 切换工厂。
- `layered` version 2 保存预算、系统规则、宿主范围、任务状态、活动数据、检索证据、摘要、最新历史引用、定义、待发压缩计数与本次注入的已完成历史来源标识。version 1 恢复时补充空来源标识，不转换活动输入或补造历史。重新注入同一配置、存储、计数器和摘要器；不序列化 SDK 或回调。见 [ADR 0015](decisions/0015-completed-run-memory.md)。
- 同时备份 Context SQLite 与 Runtime SQLite。缺失/损坏结果引用会拒绝恢复，不会重新执行已完成工具来“补数据”。
- 不手工删除工具日志、改执行版本、放宽 ReplaySafety 或伪造幂等回执。不能核验的副作用仍需已有用户审批流程。

## 密钥与模型迁移

MimoProvider 的 api_key 形参保留，但认证只来自 MIMO_API_KEY；旧部署需将密钥转为环境配置。DashScope embedding 读取 DASHSCOPE_MODEL，摘要/生成读取 DASHSCOPE_CHAT_MODEL，重排读取 DASHSCOPE_RERANK_MODEL，三者互不回退替代。未配置摘要服务时使用可观测摘要降级。

执行 `scripts/sync_context_env.py` 保留 `.env` 现有值，只追加缺失空键，并重写 `.env.example` 为占位符。复制模板后必须填写必需配置，其他占位值删除或设为空以使用默认值。禁止将本地 `.env`、SQLite、日志或真实凭据提交。

## 风险与未决事项

默认估算器不能代替提供方 tokenizer；模型窗口 W 必须由部署者核对。模型服务的摘要质量、排序效果与区域可用性需要使用授权测试数据评估，本轮自动测试全部使用替身。SQLite 向量扫描由 scan_limit 和时间限额约束，大数据集应替换为权限受控的 ANN 服务；FTS5 不可用时 BM25 扫描也有范围限制。文件加密、持久身份目录、保留/清理作业和真实多进程租约由宿主后续实现。取消与超时不能强制杀死任意已开始的外部调用。
