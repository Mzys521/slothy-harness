import type {
  AgentMode,
  ModelBinding,
  ModelSettings,
  ModelProviderUpdate,
  CodingSettings,
  CodingSettingsUpdate,
  Approval,
  ApprovalDecision,
  EventPage,
  Inspiration,
  Memory,
  Profile,
  Project,
  ProjectDirectory,
  ProjectInput,
  RunDetails,
  RunView,
  TaskRecord,
  ToolInfo,
  Workspace,
} from '../types/desktop'

interface Operations {
  workspace: [Record<string, never>, Workspace]
  model_settings: [Record<string, never>, ModelSettings]
  save_model_provider: [ModelProviderUpdate, ModelSettings]
  select_model: [ModelBinding, ModelSettings]
  remove_model_key: [{ provider_id: string; endpoint_id: string }, ModelSettings]
  test_model_connection: [ModelBinding, ModelBinding & { connected: boolean }]
  refresh_provider_models: [ModelBinding, ModelSettings]
  list_tools: [{ agent_mode?: AgentMode }, ToolInfo[]]
  update_coding_settings: [CodingSettingsUpdate, CodingSettings]
  create_project: [ProjectInput, Project]
  update_project: [
    { project_id: string; name?: string; workspace_root?: string; pinned?: boolean },
    Project,
  ]
  inspect_project_directory: [{ workspace_root: string }, ProjectDirectory]
  choose_project_directory: [
    Record<string, never>,
    { available: boolean; directory: ProjectDirectory | null },
  ]
  save_inspiration: [{ title: string; prompt: string }, Inspiration]
  create_task: [
    {
      user_input: string
      profile: Profile
      project_id: string | null
      agent_mode: AgentMode
      model_binding?: ModelBinding
    },
    TaskRecord,
  ]
  inspect_run: [{ run_id: string }, RunDetails]
  get_events: [{ run_id: string; after: number; limit: number }, EventPage]
  execute_run: [{ run_id: string }, RunView]
  interrupt_run: [{ run_id: string }, RunView]
  cancel_run: [{ run_id: string }, RunView]
  resume_run: [{ run_id: string; expected_revision: number | null }, RunView]
  get_approval: [{ run_id: string }, Approval]
  approve_tool: [
    { run_id: string; request_id: string; expected_revision: number },
    ApprovalDecision,
  ]
  reject_tool: [{ run_id: string; request_id: string; expected_revision: number }, ApprovalDecision]
  search_memory: [{ query: string }, { memories: Memory[] }]
  remember: [{ id: string; text: string; source: string }, { vector_status: string }]
}

declare global {
  interface Window {
    pywebview?: { api?: { request(method: string, payload: unknown): Promise<unknown> } }
  }
}

export class BridgeError extends Error {
  constructor(
    message: string,
    readonly code = 'transport_unavailable',
  ) {
    super(message)
    this.name = 'BridgeError'
  }
}

/** The only native/HTTP boundary. Callers can invoke only known Application operations. */
export async function request<M extends keyof Operations>(
  method: M,
  payload: Operations[M][0],
): Promise<Operations[M][1]> {
  let response: unknown
  try {
    const native = window.pywebview?.api
    if (native?.request) response = await native.request(method, payload)
    else {
      const result = await fetch(`/api/${method}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Slothy-Client': 'desktop-ui' },
        body: JSON.stringify(payload),
      })
      if (!result.ok) throw new BridgeError('本地服务无法处理请求，请刷新连接。')
      response = await result.json()
    }
  } catch (error) {
    if (error instanceof BridgeError) throw error
    throw new BridgeError('尚未连接 Slothy 本地服务，请启动桌面服务后重试。')
  }
  if (!response || typeof response !== 'object' || !('ok' in response)) {
    throw new BridgeError('本地服务返回了无效响应。', 'invalid_response')
  }
  const envelope = response as {
    ok: boolean
    data?: Operations[M][1]
    error?: { message?: string; code?: string }
  }
  if (envelope.ok !== true)
    throw new BridgeError(
      envelope.error?.message || '操作未完成，请重试。',
      envelope.error?.code || 'application_error',
    )
  if (!('data' in envelope)) throw new BridgeError('本地服务响应缺少数据。', 'invalid_response')
  return envelope.data as Operations[M][1]
}
