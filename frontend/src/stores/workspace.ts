import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import type { InjectionKey } from 'vue'
import { BridgeError, request } from '../services/bridge'
import { projectBudget, projectProcess } from '../services/eventProjection'
import type {
  AgentMode,
  ModelBinding,
  ModelProviderUpdate,
  CodingSettingsUpdate,
  Approval,
  Memory,
  Profile,
  Project,
  ProjectInput,
  RunCommand,
  RunDetails,
  RunEvent,
  Section,
  TaskRecord,
  ToolInfo,
  Workspace,
} from '../types/desktop'

export function createWorkspaceStore() {
  const workspace = ref<Workspace | null>(null)
  const tools = ref<ToolInfo[]>([])
  const connected = ref(false)
  const connecting = ref(false)
  const section = ref<Section>('harness')
  const collapsed = ref(window.innerWidth <= 640)
  const inspectorOpen = ref(window.innerWidth > 1100)
  const draft = ref('')
  const profile = ref<Profile>('quick')
  const agentMode = ref<AgentMode>('general')
  const toolsLoading = ref(false)
  const modelBusy = ref(false)
  let toolSequence = 0
  try {
    if (localStorage.getItem('slothy-agent-mode') === 'coding') agentMode.value = 'coding'
  } catch {
    /* 本地存储不可用时使用通用助手 */
  }
  const projectId = ref<string | null>(null)
  const modeDrafts: Record<AgentMode, string> = { general: '', coding: '' }
  const modeProfilesChosen: Record<AgentMode, Profile> = { general: 'quick', coding: 'quick' }
  let codingProjectId: string | null = null
  try {
    codingProjectId = localStorage.getItem('slothy-coding-project')
    if (agentMode.value === 'coding') projectId.value = codingProjectId
  } catch {
    /* 本地偏好可用时恢复 */
  }
  const selectedId = ref<string | null>(null)
  const details = ref<RunDetails | null>(null)
  const events = ref<RunEvent[]>([])
  const approval = ref<Approval | null>(null)
  const truncated = ref(false)
  const loadingTask = ref(false)
  const creatingTask = ref(false)
  const executionIds = ref<string[]>([])
  const controlBusy = ref(false)
  const approvalBusy = ref(false)
  const notice = ref('')
  const noticeKind = ref<'info' | 'error' | 'neutral'>('info')
  const memories = ref<Memory[]>([])
  const memoryQuery = ref('')
  const memoryBusy = ref(false)
  const memorySearched = ref(false)
  let epoch = 0,
    cursor = 0,
    requestSequence = 0,
    appliedSequence = 0,
    workspaceSequence = 0
  let disposed = false
  const selectedTask = computed(
    () => workspace.value?.tasks.find((task) => task.run_id === selectedId.value) || null,
  )
  const run = computed(() => details.value?.run || selectedTask.value?.run || null)
  const executing = computed(
    () => !!selectedId.value && executionIds.value.includes(selectedId.value),
  )
  const busy = computed(() => !!run.value?.busy || executing.value)
  const configured = computed(() => workspace.value?.status.model.configured === true)
  const selectedProject = computed(
    () => workspace.value?.projects.find((project) => project.id === projectId.value) || null,
  )
  const modeLabel = computed(() => (agentMode.value === 'coding' ? 'sloty coding' : 'slothy chat'))
  const codingReady = computed(
    () => agentMode.value !== 'coding' || !!selectedProject.value?.workspace_root,
  )
  const modeProfiles = computed(() =>
    agentMode.value === 'coding'
      ? workspace.value?.status.coding_profiles
      : workspace.value?.status.profiles,
  )
  const filteredTasks = computed(
    () =>
      workspace.value?.tasks.filter((task) => (task.agent_mode || 'general') === agentMode.value) ||
      [],
  )
  const projectName = computed(
    () =>
      workspace.value?.projects.find((project) => project.id === projectId.value)?.name ||
      '选择项目',
  )
  const budget = computed(() =>
    projectBudget(
      details.value?.context_config || workspace.value?.status.context_config,
      details.value,
    ),
  )
  const process = computed(() => projectProcess(events.value, run.value))
  const streamText = computed(() => {
    const chunks = events.value.filter((event) => event.event_type === 'run.model.token_chunk')
    const latest = chunks.at(-1)
    return latest
      ? chunks
          .filter(
            (event) =>
              event.generation === latest.generation && event.step_number === latest.step_number,
          )
          .map((event) => String(event.payload.text || ''))
          .join('')
      : ''
  })
  const tokenTotal = computed(() => {
    const latest = events.value.findLast(
      (event) => event.event_type === 'run.observability.token_usage',
    )
    const cumulative = latest?.payload.cumulative as { total_tokens?: number } | undefined
    return cumulative?.total_tokens ?? details.value?.usage?.total_tokens ?? null
  })

  function notify(message: string, kind: 'info' | 'error' | 'neutral' = 'info') {
    notice.value = message
    noticeKind.value = kind
  }
  function report(error: unknown) {
    if (error instanceof BridgeError && error.code === 'run_cancelled') {
      notify(error.message, 'neutral')
      return
    }
    notify(error instanceof Error ? error.message : '操作未完成，请重试。', 'error')
  }
  function current(id: string, version: number) {
    return !disposed && selectedId.value === id && epoch === version
  }

  async function refreshWorkspace() {
    const sequence = ++workspaceSequence
    const value = await request('workspace', {})
    if (!disposed && sequence === workspaceSequence) {
      workspace.value = value
      connected.value = true
    }
  }
  async function connect() {
    if (connecting.value) return
    connecting.value = true
    try {
      const [value] = await Promise.all([request('workspace', {}), refreshTools()])
      if (disposed) return
      workspace.value = value
      connected.value = true
      notice.value = ''
    } catch (error) {
      connected.value = false
      report(error)
    } finally {
      connecting.value = false
    }
  }
  async function refreshTools() {
    const sequence = ++toolSequence,
      mode = agentMode.value
    toolsLoading.value = true
    tools.value = []
    try {
      const catalog = await request('list_tools', { agent_mode: mode })
      if (!disposed && sequence === toolSequence) tools.value = catalog
    } finally {
      if (!disposed && sequence === toolSequence) toolsLoading.value = false
    }
  }
  watch(agentMode, (mode) => {
    try {
      localStorage.setItem('slothy-agent-mode', mode)
    } catch {
      /* 模式切换不依赖本地存储 */
    }
    if (connected.value) void refreshTools().catch(report)
  })
  watch(projectId, (id) => {
    if (agentMode.value === 'coding') {
      codingProjectId = id
      try {
        if (id) localStorage.setItem('slothy-coding-project', id)
        else localStorage.removeItem('slothy-coding-project')
      } catch {
        /* 业务配置由宿主保存 */
      }
    }
  })
  watch(profile, (value) => {
    modeProfilesChosen[agentMode.value] = value
  })
  watch(
    () => JSON.stringify(workspace.value?.status.coding_settings),
    (value, old) => {
      if (old && value !== old && connected.value && agentMode.value === 'coding')
        void refreshTools().catch(report)
    },
  )
  async function saveModelProvider(settings: ModelProviderUpdate) {
    modelBusy.value = true
    try {
      const value = await request('save_model_provider', settings)
      if (workspace.value) workspace.value.status.model_settings = value
      await refreshWorkspace()
      return value
    } finally {
      modelBusy.value = false
    }
  }
  async function selectModel(binding: ModelBinding) {
    if (modelBusy.value) return
    modelBusy.value = true
    try {
      const value = await request('select_model', binding)
      if (workspace.value) workspace.value.status.model_settings = value
      await refreshWorkspace()
      notify('已切换到 ' + binding.model + '，将用于新任务。')
    } finally {
      modelBusy.value = false
    }
  }
  async function removeModelKey(provider_id: string, endpoint_id: string) {
    modelBusy.value = true
    try {
      const value = await request('remove_model_key', { provider_id, endpoint_id })
      if (workspace.value) workspace.value.status.model_settings = value
      await refreshWorkspace()
      return value
    } finally {
      modelBusy.value = false
    }
  }
  async function refreshProviderModels(binding: ModelBinding) {
    modelBusy.value = true
    try {
      const value = await request('refresh_provider_models', binding)
      if (workspace.value) workspace.value.status.model_settings = value
      return value
    } finally {
      modelBusy.value = false
    }
  }
  async function saveCodingSettings(settings: CodingSettingsUpdate) {
    const value = await request('update_coding_settings', settings)
    if (workspace.value) workspace.value.status.coding_settings = value
    notify('sloty coding 设置已保存，将应用于新任务。')
    return value
  }
  async function refreshRun() {
    const id = selectedId.value,
      version = epoch,
      sequence = ++requestSequence
    if (!id) return
    const view = await request('inspect_run', { run_id: id })
    if (!current(id, version)) return
    if (sequence >= appliedSequence) {
      appliedSequence = sequence
      details.value = view
      const task = workspace.value?.tasks.find((item) => item.run_id === id)
      if (task) task.run = view.run
    }
    // Read actual cursor pages, retaining failed attempts and every generation.
    for (let pageNumber = 0; pageNumber < 5; pageNumber++) {
      const page = await request('get_events', { run_id: id, after: cursor, limit: 200 })
      if (!current(id, version)) return
      const known = new Set(events.value.map((event) => event.cursor))
      events.value.push(...page.events.filter((event) => !known.has(event.cursor)))
      events.value.sort((a, b) => a.cursor - b.cursor)
      cursor = Math.max(cursor, page.next_cursor)
      truncated.value ||= page.truncated
      if (events.value.length > 4000) {
        events.value.splice(0, events.value.length - 4000)
        truncated.value = true
      }
      if (!page.has_more) break
    }
    if (sequence !== appliedSequence) return
    if (view.run.status === 'waiting_approval' && !view.run.busy) {
      const pending = await request('get_approval', { run_id: id })
      if (current(id, version) && sequence === appliedSequence) approval.value = pending
    } else approval.value = null
  }
  function clearSelection() {
    epoch++
    selectedId.value = null
    details.value = null
    events.value = []
    cursor = 0
    approval.value = null
    truncated.value = false
    loadingTask.value = false
    appliedSequence = 0
  }
  function newTask() {
    clearSelection()
    section.value = 'harness'
    draft.value = ''
    notice.value = ''
  }
  function switchMode(mode: AgentMode) {
    if (mode === agentMode.value) return
    modeDrafts[agentMode.value] = draft.value
    modeProfilesChosen[agentMode.value] = profile.value
    clearSelection()
    agentMode.value = mode
    profile.value = modeProfilesChosen[mode]
    projectId.value = mode === 'coding' ? codingProjectId : null
    draft.value = modeDrafts[mode]
    section.value = 'harness'
    notice.value = ''
  }
  function chooseProject(id: string) {
    if (agentMode.value !== 'coding') switchMode('coding')
    if (projectId.value !== id) {
      newTask()
      projectId.value = id
    }
    section.value = 'harness'
  }
  function newProjectTask(id: string) {
    chooseProject(id)
    newTask()
  }
  function usePrompt(prompt: string) {
    newTask()
    draft.value = prompt
  }
  async function selectTask(task: TaskRecord) {
    if (task.available === false) {
      notify('此任务的快照不可用，请新建任务。')
      return
    }
    switchMode(task.agent_mode || 'general')
    clearSelection()
    selectedId.value = task.run_id
    profile.value = task.profile
    section.value = 'harness'
    projectId.value = agentMode.value === 'coding' ? task.project_id : null
    const version = epoch
    loadingTask.value = true
    try {
      await refreshRun()
    } catch (error) {
      if (current(task.run_id, version)) report(error)
    } finally {
      if (current(task.run_id, version)) loadingTask.value = false
    }
  }
  async function execute(id: string, resume = false) {
    if (executionIds.value.includes(id)) return
    executionIds.value.push(id)
    if (resume && selectedId.value === id) notice.value = ''
    const revision = run.value?.run_id === id ? run.value.snapshot_revision : null
    try {
      if (resume) await request('resume_run', { run_id: id, expected_revision: revision })
      else await request('execute_run', { run_id: id })
    } catch (error) {
      if (selectedId.value === id) report(error)
    } finally {
      executionIds.value = executionIds.value.filter((value) => value !== id)
      await refreshWorkspace().catch(report)
      if (selectedId.value === id) await refreshRun().catch(report)
    }
  }
  async function send() {
    if (
      !draft.value.trim() ||
      creatingTask.value ||
      busy.value ||
      !connected.value ||
      !configured.value ||
      !codingReady.value ||
      toolsLoading.value ||
      modelBusy.value
    )
      return
    creatingTask.value = true
    notice.value = ''
    const creationVersion = epoch,
      sourceDraft = draft.value
    const text = sourceDraft.trim(),
      selectedProfile = profile.value,
      selectedMode = agentMode.value,
      selectedProjectId = agentMode.value === 'coding' ? projectId.value : null
    const chosenModel = workspace.value?.status.model_settings?.selection
    const modelBinding = chosenModel ? { ...chosenModel } : undefined
    try {
      const task = await request('create_task', {
        user_input: text,
        profile: selectedProfile,
        agent_mode: selectedMode,
        project_id: selectedProjectId,
        ...(modelBinding ? { model_binding: modelBinding } : {}),
      })
      // Creation is acknowledged before execution; a refresh failure never causes a duplicate create.
      if (workspace.value) workspace.value.tasks.unshift(task)
      if (agentMode.value === selectedMode && epoch === creationVersion) {
        const selecting = selectTask(task)
        const selectionVersion = epoch
        await selecting
        if (current(task.run_id, selectionVersion) && draft.value === sourceDraft) draft.value = ''
      }
      if (modeDrafts[selectedMode] === sourceDraft) modeDrafts[selectedMode] = ''
      creatingTask.value = false
      await execute(task.run_id)
    } catch (error) {
      report(error)
    } finally {
      creatingTask.value = false
    }
  }
  async function control(command: RunCommand) {
    const id = selectedId.value
    if (!id || controlBusy.value) return
    if (command === 'execute_run' || command === 'resume_run') {
      await execute(id, command === 'resume_run')
      return
    }
    controlBusy.value = true
    try {
      await request(command, { run_id: id })
      if (selectedId.value === id) await refreshRun()
    } catch (error) {
      if (selectedId.value === id) report(error)
    } finally {
      controlBusy.value = false
    }
  }
  async function decide(approved: boolean) {
    const pending = approval.value
    if (!pending || pending.decision || approvalBusy.value) return
    approvalBusy.value = true
    try {
      await request(approved ? 'approve_tool' : 'reject_tool', {
        run_id: pending.run_id,
        request_id: pending.request_id,
        expected_revision: pending.snapshot_revision,
      })
      if (selectedId.value === pending.run_id) {
        notify(
          approved
            ? '已批准本次尝试，点击“继续执行”恢复任务。'
            : '已拒绝本次尝试，点击“继续执行”将决定交回模型。',
        )
        await refreshRun()
      }
    } catch (error) {
      report(error)
    } finally {
      approvalBusy.value = false
    }
  }
  async function saveProject(input: ProjectInput, project?: Project | null) {
    const value = project
      ? await request('update_project', { project_id: project.id, ...input })
      : await request('create_project', input)
    await refreshWorkspace()
    chooseProject(value.id)
    notify(project ? '项目已更新，目录设置应用于新任务。' : '项目已创建。')
    return value
  }
  async function pinProject(project: Project) {
    const value = await request('update_project', {
      project_id: project.id,
      pinned: !project.pinned,
    })
    await refreshWorkspace()
    return value
  }
  async function saveInspiration(title: string, prompt: string) {
    await request('save_inspiration', { title: title.trim(), prompt: prompt.trim() })
    await refreshWorkspace()
    notify('灵感已保存。')
  }
  async function searchMemory() {
    if (!memoryQuery.value.trim() || memoryBusy.value) return
    memoryBusy.value = true
    try {
      const result = await request('search_memory', { query: memoryQuery.value.trim() })
      memories.value = result.memories
      memorySearched.value = true
    } catch (error) {
      report(error)
    } finally {
      memoryBusy.value = false
    }
  }
  async function remember(text: string) {
    const result = await request('remember', {
      id: crypto.randomUUID(),
      text: text.trim(),
      source: 'desktop',
    })
    notify(
      result.vector_status === 'embedding_fallback'
        ? '记忆已保存，当前可使用关键词检索。'
        : '记忆已保存。',
    )
  }
  function exportLogs() {
    if (!events.value.length) {
      notify('选择有事件记录的任务后即可导出。')
      return
    }
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(events.value, null, 2)], { type: 'application/json' }),
    )
    const link = document.createElement('a')
    link.href = url
    link.download = `slothy-${selectedId.value}-events.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  let timer: ReturnType<typeof setTimeout> | undefined,
    ticks = 0
  async function poll() {
    if (disposed) return
    try {
      if (connected.value) {
        if (selectedId.value && selectedTask.value?.available !== false) await refreshRun()
        if (++ticks % 5 === 0) await refreshWorkspace()
      }
    } catch (error) {
      report(error)
    } finally {
      if (!disposed)
        timer = setTimeout(() => {
          void poll()
        }, 700)
    }
  }
  onMounted(() => {
    void connect()
    timer = setTimeout(() => {
      void poll()
    }, 700)
  })
  onUnmounted(() => {
    disposed = true
    epoch++
    clearTimeout(timer)
  })
  return {
    workspace,
    tools,
    connected,
    connecting,
    section,
    collapsed,
    inspectorOpen,
    draft,
    profile,
    agentMode,
    modeLabel,
    switchMode,
    chooseProject,
    newProjectTask,
    selectedProject,
    codingReady,
    modeProfiles,
    toolsLoading,
    modelBusy,
    saveModelProvider,
    selectModel,
    removeModelKey,
    refreshProviderModels,
    saveCodingSettings,
    projectId,
    selectedId,
    details,
    events,
    approval,
    truncated,
    loadingTask,
    creatingTask,
    busy,
    controlBusy,
    approvalBusy,
    notice,
    noticeKind,
    memories,
    memoryQuery,
    memoryBusy,
    memorySearched,
    selectedTask,
    run,
    configured,
    filteredTasks,
    projectName,
    budget,
    process,
    streamText,
    tokenTotal,
    notify,
    report,
    connect,
    refreshWorkspace,
    newTask,
    usePrompt,
    selectTask,
    send,
    control,
    decide,
    saveProject,
    pinProject,
    saveInspiration,
    searchMemory,
    remember,
    exportLogs,
  }
}

export type WorkspaceStore = ReturnType<typeof createWorkspaceStore>
export const workspaceKey: InjectionKey<WorkspaceStore> = Symbol('slothy-workspace')
export function useWorkspace() {
  const store = inject(workspaceKey)
  if (!store) throw new Error('Workspace must be provided by the application shell.')
  return store
}
