import type {
  BudgetView,
  ContextConfig,
  ProcessNode,
  RunDetails,
  RunEvent,
  RunView,
} from '../types/desktop'

export const statusLabels: Record<string, string> = {
  idle: '待启动',
  running: '运行中',
  thinking: '思考中',
  waiting_tool: '等待工具',
  executing_tool: '执行工具',
  waiting_approval: '等待批准',
  suspended: '已暂停',
  completed: '已完成',
  failed: '执行失败',
  cancelled: '已取消',
}
export const formatTokens = (value: number) =>
  value >= 10000 ? `${(value / 1000).toFixed(1)}k` : value.toLocaleString('zh-CN')
export const formatDuration = (value: number) =>
  value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`

/** Project observations only: this never predicts or advances the runtime state. */
export function projectProcess(events: RunEvent[], run: RunView | null): ProcessNode[] {
  const nodes: ProcessNode[] = []
  const calls = new Map<string, ProcessNode>()
  let model: ProcessNode | undefined
  let tool: ProcessNode | undefined
  for (const event of events) {
    const p = event.payload
    const callId = typeof p.call_id === 'string' ? p.call_id : ''
    const key = `${event.generation}:${callId}`
    const target = callId ? calls.get(key) : tool
    if (event.event_type === 'run.model.request_started') {
      model = {
        id: `model-${event.cursor}`,
        name: '模型请求',
        kind: 'model',
        status: 'running',
        label: '思考中',
        detail: '读取上下文并生成下一步响应',
        step: event.step_number,
        generation: event.generation,
        duration: null,
        retries: 0,
      }
      nodes.push(model)
      tool = undefined
    } else if (event.event_type === 'run.model.responded' && model) {
      model.status = 'success'
      model.label = Number(p.tool_call_count) ? `请求 ${p.tool_call_count} 个工具` : '响应已生成'
      model.duration = Number(p.duration_ms || 0)
    } else if (event.event_type === 'run.tool.call_started') {
      tool = {
        id: `tool-${event.cursor}`,
        name: String(p.name || '工具调用'),
        kind: 'tool',
        status: 'running',
        label: '执行中',
        detail: '参数校验 → 策略与权限检查 → 执行',
        step: event.step_number,
        generation: event.generation,
        callId,
        duration: null,
        retries: 0,
      }
      nodes.push(tool)
      if (callId) calls.set(key, tool)
    } else if (event.event_type === 'run.tool.call_ended' && target) {
      target.status = p.is_error ? 'failed' : 'success'
      if (!['策略拦截', '已拒绝'].includes(target.label))
        target.label = p.is_error ? '返回错误' : '已完成'
      target.duration = Number(p.duration_ms || 0)
    } else if (event.event_type === 'run.tool.progress' && target) {
      target.detail = String(p.message || '正在执行')
      if (typeof p.completed === 'number')
        target.progress = {
          completed: p.completed,
          total: typeof p.total === 'number' ? p.total : null,
        }
    } else if (
      (event.event_type === 'run.tool.error' || event.event_type === 'run.tool.timeout') &&
      target
    ) {
      target.status = 'failed'
      target.label = event.event_type.endsWith('timeout') ? '执行超时' : '执行失败'
    } else if (
      (event.event_type === 'run.model.error' || event.event_type === 'run.model.timeout') &&
      model
    ) {
      model.status = 'failed'
      model.label = event.event_type.endsWith('timeout') ? '请求超时' : '请求失败'
    } else if (event.event_type === 'run.policy.triggered' && p.decision === 'retry') {
      const retryTarget = target || model
      if (retryTarget) {
        retryTarget.retries++
        retryTarget.label = '失败后重试'
      }
    } else if (event.event_type === 'run.tool.approval_requested' && target) {
      target.status = 'waiting'
      target.label = '等待批准'
    } else if (event.event_type === 'run.tool.approval_resolved' && target) {
      target.status = p.approved ? 'waiting' : 'failed'
      target.label = p.approved ? '已批准，等待恢复' : '已拒绝'
    } else if (event.event_type === 'run.policy.guardrail_blocked' && target) {
      target.status = 'failed'
      target.label = '策略拦截'
    }
  }
  // A recorded approval belongs to its original generation; a later generation
  // proves resume has occurred without claiming the tool itself succeeded.
  for (const node of nodes) {
    if (node.label === '已批准，等待恢复' && run && run.generation > node.generation) {
      node.status = 'stopped'
      node.label = '已批准本次尝试'
    }
  }
  if (run && !run.busy) {
    for (const node of nodes.filter((n) => n.status === 'running')) {
      node.status = run.status === 'failed' ? 'failed' : 'stopped'
      node.label = statusLabels[run.status] || run.status
    }
  }
  return nodes
}

export function projectBudget(
  config: ContextConfig | undefined | null,
  details: RunDetails | null,
): BudgetView {
  if (!config) return { used: null, limit: 0, segments: [] }
  const layers = details?.context_report?.layer_tokens
  return {
    used: details?.context_report?.input_tokens ?? null,
    limit:
      details?.context_report?.input_budget ??
      Math.max(0, config.model_window - config.output_reserve - config.safety_margin),
    segments: [
      {
        name: 'System Prompt',
        label: '系统与工具',
        used: layers ? (layers.system_prompt || 0) + (layers.tool_schemas || 0) : null,
        limit: config.system_prompt + config.tool_schemas,
      },
      {
        name: 'Task State',
        label: '任务状态',
        used: layers?.task_state ?? null,
        limit: config.task_state,
      },
      {
        name: 'Long-Term Memory',
        label: '长期记忆',
        used: layers?.long_term_memory ?? null,
        limit: config.long_term_memory,
      },
      {
        name: 'Working Memory',
        label: '工作记忆',
        used: layers ? (layers.working_memory || 0) + (layers.user_input_buffer || 0) : null,
        limit: config.working_memory + config.user_input_buffer,
      },
      {
        name: 'Output Buffer',
        label: '输出预留',
        used: config.output_reserve,
        limit: config.output_reserve,
        reserved: true,
      },
    ],
  }
}
