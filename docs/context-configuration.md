# Context 配置与模型能力

所有 token/字符预算在 ContextConfig / RetrievalConfig 中定义，可通过同名环境项覆盖。Infrastructure 负责加载环境，Core 不读环境。生产调用 assemble_context_components(config=None, retrieval=None) 自动读取；显式配置对象优先。演示程序为验证而显式选择 8192 输入预算，其他层默认仍来自配置。

## 模型与存储

| 环境项 | 用途 |
| --- | --- |
| DASHSCOPE_API_KEY | 仅认证；只从环境读取，不保存到 Core/快照/日志 |
| DASHSCOPE_MODEL | embedding，例如部署者已选用的 qwen3.7-text-embedding-flash；不允许生成文本 |
| DASHSCOPE_CHAT_MODEL | 摘要与文本生成；必须为 chat 模型 |
| DASHSCOPE_RERANK_MODEL | 可选重排服务；缺失或调用失败使用融合排序 |
| DASHSCOPE_BASE_URL | 原生服务基础地址，包含 api/v1；用于原生重排路由 |
| DASHSCOPE_BASE_URL_WITH_OPENAI | 兼容接口基础地址；追加 embeddings/chat/completions 或 reranks |
| SLOTHY_CONTEXT_DB | 默认 .slothy/context.sqlite3，宿主配置，模型不能指定 |
| MIMO_API_KEY / MIMO_BASE_URL / MIMO_MODEL | 旧演示提供方兼容；api_key 构造参数不作为认证源 |

基础地址必须为无内嵌凭证的 HTTPS URL，不带查询或 fragment；HTTP 适配器拒绝重定向，错误只返回固定分类。具体区域和兼容路径依模型平台控制台配置，不自动猜测地址。重排路由按[官方重排 API](https://help.aliyun.com/zh/model-studio/text-rerank-api)区分：qwen3-rerank 使用兼容接口 reranks，其余已支持文本模型使用原生 services/rerank/text-rerank/text-rerank。

没有 CHAT 配置时滚动摘要降级；只有 embedding 可用不会调用它生成摘要。remote=False 完全不创建模型适配器。remote=True 启用已配置服务；显式错误的模型类型或地址在组装时拒绝。

## ContextConfig

环境前缀 SLOTHY_CONTEXT_；下表数值只是公开默认配置，不是本地环境值。

| 字段 | 默认值 |
| --- | --- |
| model_window | 32768 |
| output_reserve | 4096 |
| safety_margin | 512 |
| system_prompt | 4096 |
| tool_schemas | 2048 |
| tool_schema_overhead_tokens | 32 |
| task_state | 2048 |
| long_term_memory | 4096 |
| working_memory | 6144 |
| user_input_buffer | 2048 |
| recent_turns | 6 |
| summary_tokens | 1024 |
| summary_input_tokens | 6144 |
| summary_timeout_seconds | 15 |
| observation_tokens | 512 |
| observation_chars | 2048 |
| observation_page_chars | 4096 |
| history_messages | 2000 |

W = model_window，O = output_reserve，输入上限 = W - O - safety_margin。W 必须核对生成模型的实际窗口与部署规格；系统不利用 embedding 窗口，也不声称 SDK 会自动发现 W。output_reserve 传为 max_tokens；Qwen chat 禁用思考，其他平台须核对生成输出计数语义。

各层计数包含 XML/JSON 转义与消息开销。tool_schemas 同时包含 XML 展示、模型原生工具参数和每工具的协议余量。可选 TokenEstimator.estimate_tools(definitions) 提供精确原生定义计数；未提供则使用 neutral JSON + tool_schema_overhead_tokens 的保守补偿。默认启发式不用于计费，生产可注入精确 TokenEstimator；safety_margin 不能代替 tokenizer。

recent_turns 是完整分组上限，预算不足会进一步收缩。summary_tokens 包括滚动摘要元数据，summary_input_tokens 在 chat 适配器中包含摘要指令和 XML 包装。observation_page_chars 是请求页长上限，实际页长还受 observation_tokens/observation_chars 约束，游标按实际交付长度推进。history_messages 限制活动消息，不限制 SQLite 总容量。

## RetrievalConfig

环境前缀 SLOTHY_RAG_。

| 字段 | 默认值 |
| --- | --- |
| candidate_limit | 20 |
| top_k | 4 |
| vector_weight | 0.55 |
| bm25_weight | 0.3 |
| entity_weight | 0.15 |
| time_weight | 0.1 |
| half_life_days | 30 |
| vector_timeout_seconds | 3 |
| bm25_timeout_seconds | 1 |
| entity_timeout_seconds | 1 |
| rerank_timeout_seconds | 3 |
| min_score | 0 |
| query_chars | 2048 |
| document_chars | 4096 |
| scan_limit | 10000 |
| bm25_k1 | 1.2 |
| bm25_b | 0.75 |
| max_entity_filters | 16 |
| entity_value_chars | 256 |

通道分别归一化相关性分数并使用对应权重；time_weight × 2^(-age_days/half_life_days) 为时间加权。所有通道失败时工具返回 retrieval_unavailable，健康通道的空结果仍是正常空值。重排后 TopK 默认 4；无效索引、非有限分数或失败会回退融合结果。

scan_limit 限制本地向量扫描与无 FTS5 的 BM25 回退；FTS5 查询使用全文索引，实体过滤在 LIMIT 前执行。大规模语义库应替换 RetrievalChannel。max_entity_filters/entity_value_chars 控制不可信过滤器大小；模型不能选择 owner 或文件路径。

## 注入能力与时限

assemble_context_components 可注入 store、estimator、summarizer、observer 和配置。HybridRetriever 可独立注入三个通道、Reranker 和 invoker。Infrastructure BoundedInvoker 默认容量 4，超时立即忽略晚到结果；容量耗尽立即降级，线程结束后释放容量，不强制杀线程。服务适配器同时设置 I/O 超时。

生产 MemoryService 的 embedding 写入应注入 components.retriever.invoker，以同时获得绝对等待时限；不注入时需要 embedding 实现遵守自身 I/O 超时契约。SQLiteContextStore 的连接时限、DashScopeJSONClient 的响应字节上限、隔离容量也可在各适配器构造参数中配置。

Extract Schema 由宿主配置 create_context/create_executor 的 extract_schemas；两者应使用相同字段规则。observer 只接收安全计数报告，须快速返回；异常隔离不改变执行结果。

## 环境模板

.env 与 .env.example 键名一致。.env.example 的每个值都是占位符，不包含真实密钥或复制来的本地配置。运行：

```powershell
.\.venv\Scripts\python.exe scripts/sync_context_env.py
```

同步脚本只追加缺失空键，保留本地值，不打印值。复制模板后填写必需项，删除可选占位值或设为空以使用默认配置；未替换的数字占位符会被明确拒绝，不能默认为有效配置。模型、日志或测试不得读取并传播真实 .env 值。运行数据位于已忽略的 .slothy/，存储备份、加密和保留策略由宿主负责。
