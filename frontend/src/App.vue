<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import AppIcon from './components/AppIcon.vue'
import WorkspaceSidebar from './components/WorkspaceSidebar.vue'
import ContextBudget from './components/ContextBudget.vue'
import ModalDialog from './components/ModalDialog.vue'
import ProjectDialog from './components/ProjectDialog.vue'
import HarnessView from './views/HarnessView.vue'
import ToolsView from './views/ToolsView.vue'
import MemoryView from './views/MemoryView.vue'
import InspirationView from './views/InspirationView.vue'
import LogsView from './views/LogsView.vue'
import SettingsView from './views/SettingsView.vue'
import SchedulesView from './views/SchedulesView.vue'
import { createWorkspaceStore, workspaceKey } from './stores/workspace'
import { useAppearance } from './stores/appearance'
import { statusLabels } from './services/eventProjection'
import type { Project, Section, TaskRecord } from './types/desktop'

const store = createWorkspaceStore()
provide(workspaceKey, store)
const {
  workspace,
  tools,
  connected,
  connecting,
  section,
  collapsed,
  agentMode,
  modeLabel,
  projectId,
  selectedProject,
  selectedId,
  selectedTask,
  filteredTasks,
  notice,
  noticeKind,
  budget,
  run,
  tokenTotal,
  details,
  configured,
  connect,
  newTask,
  usePrompt,
  selectTask,
  switchMode,
  chooseProject,
  newProjectTask,
  pinProject,
  report,
  saveInspiration,
  remember,
} = store
const { resolved, setAppearance } = useAppearance()
const harness = ref<InstanceType<typeof HarnessView> | null>(null)
type Dialog = 'inspiration' | 'memory' | 'search' | 'plugins'
const dialog = ref<Dialog | null>(null)
const projectDialog = ref(false)
const editingProject = ref<Project | null>(null)
const dialogName = ref(''),
  dialogText = ref(''),
  dialogError = ref(''),
  search = ref(''),
  dialogBusy = ref(false)
const labels: Record<Section, string> = {
  harness: '工作台',
  tools: '工具链',
  memory: '长期记忆',
  inspiration: '灵感库',
  logs: '运行日志',
  schedules: '定时任务',
  settings: '设置',
}
const dialogTitle = computed(() =>
  dialog.value
    ? {
        inspiration: '保存灵感',
        memory: '保存长期记忆',
        search: '搜索任务',
        plugins: '工具与插件',
      }[dialog.value]
    : '',
)
const searchResults = computed(() =>
  filteredTasks.value.filter((task) =>
    (task.title + ' ' + task.goal)
      .toLocaleLowerCase()
      .includes(search.value.trim().toLocaleLowerCase()),
  ),
)
const breadcrumb = computed(() =>
  section.value === 'harness' && agentMode.value === 'coding'
    ? selectedProject.value?.name || '工作台'
    : labels[section.value],
)
watch(
  [section, selectedTask, modeLabel],
  () => {
    document.title =
      (section.value === 'harness' && selectedTask.value
        ? selectedTask.value.title
        : labels[section.value]) +
      ' · ' +
      modeLabel.value
  },
  { immediate: true },
)
function openDialog(value: Dialog) {
  dialog.value = value
  dialogName.value = ''
  dialogText.value = ''
  dialogError.value = ''
  search.value = ''
}
function openProject(project: Project | null = null) {
  editingProject.value = project
  projectDialog.value = true
}
async function startFresh() {
  newTask()
  await nextTick()
  harness.value?.focus()
}
async function setPrompt(value: string) {
  usePrompt(value)
  await nextTick()
  harness.value?.focus()
}
function showTools() {
  dialog.value = null
  section.value = 'tools'
}
async function chooseTask(task: TaskRecord) {
  dialog.value = null
  await selectTask(task)
}
async function saveDialog() {
  if (dialogBusy.value) return
  dialogBusy.value = true
  dialogError.value = ''
  try {
    if (dialog.value === 'inspiration') await saveInspiration(dialogName.value, dialogText.value)
    else if (dialog.value === 'memory') await remember(dialogText.value)
    dialog.value = null
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '保存未完成，请重试。'
  } finally {
    dialogBusy.value = false
  }
}
function shortcuts(event: KeyboardEvent) {
  if (dialogBusy.value || projectDialog.value || event.altKey || !(event.ctrlKey || event.metaKey))
    return
  if (event.key.toLowerCase() === 'k') {
    event.preventDefault()
    dialog.value = null
    void startFresh()
  }
  if (event.key.toLowerCase() === 'p') {
    event.preventDefault()
    openDialog('search')
  }
}
onMounted(() => window.addEventListener('keydown', shortcuts))
onUnmounted(() => window.removeEventListener('keydown', shortcuts))
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': collapsed }">
    <WorkspaceSidebar
      :collapsed="collapsed"
      :section="section"
      :connected="connected"
      :mode="agentMode"
      :projects="workspace?.projects || []"
      :tasks="filteredTasks"
      :selected-id="selectedId"
      :project-id="projectId"
      :user="workspace?.status.user.name || '本地用户'"
      @toggle="collapsed = !collapsed"
      @mode="switchMode"
      @new-task="startFresh"
      @navigate="section = $event"
      @project="chooseProject"
      @create-project="openProject()"
      @edit-project="openProject($event)"
      @pin-project="pinProject($event).catch(report)"
      @project-task="newProjectTask"
      @select="selectTask"
      @search="openDialog('search')"
    />
    <main class="workspace-main">
      <header class="workspace-header">
        <div class="workspace-breadcrumb">
          <AppIcon :name="agentMode === 'coding' ? 'code' : 'message'" :size="16" />
          <span>{{ modeLabel }}</span>
          <span class="breadcrumb-slash">/</span>
          <strong>{{ breadcrumb }}</strong>
        </div>
        <div class="header-actions">
          <button
            class="icon-button appearance-toggle"
            :aria-label="resolved === 'light' ? '切换到深色主题' : '切换到浅色主题'"
            :title="resolved === 'light' ? '深色主题' : '浅色主题'"
            @click="setAppearance(resolved === 'light' ? 'dark' : 'light')"
          >
            <AppIcon :name="resolved === 'light' ? 'moon' : 'sun'" :size="17" />
          </button>
          <button class="connection-control" :disabled="connecting" @click="connect">
            <i class="connection-dot" :class="{ online: connected }" />
            <span>
              {{ connecting ? '正在连接' : connected ? '本地服务已连接' : '连接本地服务' }}
            </span>
            <AppIcon v-if="!connected" name="refresh" :size="13" />
          </button>
        </div>
      </header>
      <div v-if="notice" class="notice-bar" :class="noticeKind" role="status">
        <AppIcon
          :name="noticeKind === 'error' ? 'warning' : noticeKind === 'neutral' ? 'stop' : 'check'"
          :size="15"
        />
        <span>{{ notice }}</span>
        <button class="icon-button" aria-label="关闭提示" @click="notice = ''">
          <AppIcon name="close" :size="14" />
        </button>
      </div>
      <HarnessView v-if="section === 'harness'" ref="harness" @create-project="openProject()" />
      <div v-else class="page-scroll">
        <ToolsView
          v-if="section === 'tools'"
          @prompt="setPrompt"
          @plugins="openDialog('plugins')"
        />
        <MemoryView v-else-if="section === 'memory'" @remember="openDialog('memory')" />
        <InspirationView
          v-else-if="section === 'inspiration'"
          @save="openDialog('inspiration')"
          @prompt="setPrompt"
        />
        <LogsView v-else-if="section === 'logs'" />
        <SettingsView v-else-if="section === 'settings'" />
        <SchedulesView v-else @new-task="startFresh" />
      </div>
    </main>
    <ContextBudget
      :budget="budget"
      :run="run"
      :tokens="tokenTotal"
      :model="details?.model || workspace?.status.model.name || null"
      :configured="configured"
    />
    <ProjectDialog :open="projectDialog" :project="editingProject" @close="projectDialog = false" />
    <ModalDialog
      :open="dialog !== null"
      :title="dialogTitle"
      :busy="dialogBusy"
      @close="dialog = null"
    >
      <template v-if="dialog === 'search'">
        <div class="search-form modal-search">
          <AppIcon name="search" :size="17" />
          <input
            v-model="search"
            aria-label="搜索任务名称"
            placeholder="输入任务标题或内容…"
            autofocus
          />
        </div>
        <div class="search-results">
          <button v-for="task in searchResults" :key="task.run_id" @click="chooseTask(task)">
            <AppIcon name="logs" :size="16" />
            <span>{{ task.title }}</span>
            <small>
              {{
                task.available === false ? '快照不可用' : statusLabels[task.run?.status || 'idle']
              }}
            </small>
          </button>
          <p v-if="!searchResults.length" class="inline-note">
            {{ search ? '没有找到匹配的任务。' : '还没有任务记录。' }}
          </p>
        </div>
        <p class="modal-footnote">{{ modeLabel }} · Ctrl K 新建任务 · Esc 关闭</p>
      </template>
      <template v-else-if="dialog === 'plugins'">
        <span class="neutral-badge">插件服务尚未接入</span>
        <p class="modal-description">当前可使用已注册工具，外部插件安装将在服务接入后提供。</p>
        <div class="plugin-inventory">
          <div v-for="tool in tools" :key="tool.name">
            <AppIcon name="tool" :size="16" />
            <strong>{{ tool.name }}</strong>
            <span>已注册</span>
          </div>
        </div>
        <button class="secondary-button" @click="showTools">
          查看工具链
          <AppIcon name="chevron" :size="14" />
        </button>
      </template>
      <form v-else class="dialog-form" @submit.prevent="saveDialog">
        <label v-if="dialog === 'inspiration'">
          灵感标题
          <input
            v-model="dialogName"
            maxlength="100"
            required
            autofocus
            placeholder="给它一个简洁的名字"
          />
        </label>
        <label>
          {{ dialog === 'memory' ? '记忆内容' : '任务提示' }}
          <textarea
            v-model="dialogText"
            :maxlength="dialog === 'memory' ? 4096 : 8000"
            rows="5"
            :autofocus="dialog === 'memory'"
            required
            placeholder="写下你希望保留的内容…"
          />
        </label>
        <p v-if="dialogError" class="error-inline" role="alert">{{ dialogError }}</p>
        <div class="dialog-actions">
          <button
            type="button"
            class="secondary-button"
            :disabled="dialogBusy"
            @click="dialog = null"
          >
            取消
          </button>
          <button class="primary-button" :disabled="dialogBusy || !connected">
            {{ dialogBusy ? '保存中…' : '保存' }}
          </button>
        </div>
      </form>
    </ModalDialog>
  </div>
</template>
