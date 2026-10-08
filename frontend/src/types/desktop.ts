/** Application JSON projections. These are UI contracts, never Core entities. */
export type Profile = 'quick' | 'advanced'
export type AgentMode = 'general' | 'coding'
export interface ModelBinding {
  provider_id: string
  endpoint_id: string
  model: string
}
export interface ModelProviderSettings {
  id: string
  name: string
  default_model: string
  models: string[]
  model: string
  endpoint_id: string
  configured: boolean
  endpoints: { id: string; label: string; base_url: string; configured: boolean }[]
  documentation_url: string
  key_url: string
  can_list_models: boolean
}
export interface ModelSettings {
  providers: ModelProviderSettings[]
  selection: ModelBinding | null
  storage_kind: 'windows_dpapi' | 'session'
}
export type ModelProviderUpdate = ModelBinding & { api_key?: string }
export interface CodingSettings {
  workspace_root: string | null
  allow_edits: boolean
  allowed_checks: string[]
  check_timeout_seconds: number
}
export type CodingSettingsUpdate = Omit<CodingSettings, 'workspace_root'> & {
  workspace_root?: string | null
}
export interface ProfileLimits {
  label: string
  max_steps: number
  timeout_seconds: number
}
export type Section =
  'harness' | 'tools' | 'memory' | 'inspiration' | 'logs' | 'schedules' | 'settings'
export type RunCommand = 'execute_run' | 'interrupt_run' | 'cancel_run' | 'resume_run'

export interface RunView {
  run_id: string
  status: string
  busy: boolean
  max_steps: number
  step_count: number
  steps: { number: number; status: string; call_ids: string[]; duration_ms: number }[]
  duration_ms: number
  generation: number
  snapshot_revision: number | null
  output: string | null
  error_code: string | null
  approval_request_id: string | null
  cancel_requested: boolean
  interrupt_requested: boolean
  approval_decision: string | null
}

export interface TaskRecord {
  run_id: string
  title: string
  goal: string
  profile: Profile
  agent_mode?: AgentMode
  coding_binding?: CodingSettings
  model_binding?: ModelBinding
  project_id: string | null
  run: RunView | null
  available?: boolean
}
export interface Project {
  id: string
  name: string
  workspace_root?: string | null
  repository?: { label: string; url: string } | null
  pinned?: boolean
}
export interface ProjectDirectory {
  workspace_root: string
  repository?: Project['repository']
}
export interface ProjectInput {
  name: string
  workspace_root: string
}
export interface Inspiration {
  id: string
  title: string
  prompt: string
}
export interface ContextConfig {
  model_window: number
  output_reserve: number
  safety_margin: number
  system_prompt: number
  tool_schemas: number
  task_state: number
  long_term_memory: number
  working_memory: number
  user_input_buffer: number
}
export interface Workspace {
  status: {
    name: string
    version: string
    user: { name: string; id: string }
    model: { configured: boolean; provider: string | null; name: string | null }
    model_settings?: ModelSettings
    context_config: ContextConfig
    profiles: Record<Profile, ProfileLimits>
    coding_profiles: Record<Profile, ProfileLimits>
    agent_modes: Record<AgentMode, { label: string }>
    coding_settings: CodingSettings
    check_presets: { id: string; label: string }[]
    capabilities: Record<string, boolean>
  }
  tasks: TaskRecord[]
  projects: Project[]
  inspirations: Inspiration[]
}
export interface TaskState {
  task_id: string
  goal: string
  plan: string[]
  completed_steps: string[]
  todo_list: string[]
  entities: Record<string, string>
}
export interface RunDetails {
  run: RunView
  task_state: TaskState
  context_report: {
    input_tokens: number
    input_budget: number
    output_reserve: number
    layer_tokens: Record<string, number>
    actions: string[]
    summary_failures: number
  } | null
  context_config: ContextConfig | null
  model: string | null
  usage?: { total_tokens: number }
}
export interface RunEvent {
  cursor: number
  event_type: string
  run_id: string
  sequence: number
  step_number: number | null
  occurred_at: number
  generation: number
  status: string
  payload: Record<string, unknown>
}
export interface EventPage {
  events: RunEvent[]
  next_cursor: number
  has_more: boolean
  truncated: boolean
}
export interface ToolInfo {
  name: string
  description: string
  replay_safety: string
  parameters: Record<string, unknown>
  timeout_seconds: number | null
}
export interface Approval {
  request_id: string
  run_id: string
  tool_name: string
  reason: string
  arguments: Record<string, unknown>
  attempt: number
  snapshot_revision: number
  decision: string | null
}
export interface ApprovalDecision {
  request_id: string
  approved: boolean
  actor_id: string
  snapshot_revision: number
}
export interface Memory {
  id: string
  text: string
  source: string
  score: number
}
export interface BudgetSegment {
  name: string
  label: string
  used: number | null
  limit: number
  reserved?: boolean
}
export interface BudgetView {
  used: number | null
  limit: number
  segments: BudgetSegment[]
}
export interface ProcessNode {
  id: string
  name: string
  kind: 'model' | 'tool'
  status: 'running' | 'success' | 'failed' | 'waiting' | 'stopped'
  label: string
  detail: string
  step: number | null
  generation: number
  callId?: string
  duration: number | null
  retries: number
  progress?: { completed: number; total: number | null }
}
