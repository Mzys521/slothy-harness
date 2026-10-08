<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import TaskComposer from '../components/TaskComposer.vue'
import RunStatus from '../components/RunStatus.vue'
import RunTimeline from '../components/RunTimeline.vue'
import ApprovalCard from '../components/ApprovalCard.vue'
import RunInspector from '../components/RunInspector.vue'
import { formatDuration } from '../services/eventProjection'
import { useWorkspace } from '../stores/workspace'
const emit = defineEmits<{ createProject: [] }>()
const {
  connected,
  configured,
  modelBusy,
  draft,
  modeLabel,
  agentMode,
  codingReady,
  toolsLoading,
  selectedId,
  selectedTask,
  run,
  busy,
  creatingTask,
  controlBusy,
  approvalBusy,
  details,
  events,
  approval,
  budget,
  inspectorOpen,
  process,
  truncated,
  streamText,
  loadingTask,
  tools,
  section,
  send,
  control,
  decide,
  usePrompt,
  notify,
} = useWorkspace()
const composer = ref<InstanceType<typeof TaskComposer> | null>(null)
const scroll = ref<HTMLElement | null>(null)
const following = ref(true)
const output = computed(() => run.value?.output || streamText.value)
const reason = computed(() =>
  !connected.value
    ? '连接本地服务后即可开始'
    : !codingReady.value
      ? '请在左侧选择项目并添加源文件夹'
      : !configured.value
        ? '配置文本模型后即可发送'
        : toolsLoading.value
          ? '正在加载模式工具…'
          : '',
)
const generalSuggestions = [
  {
    title: '计算与验证',
    caption: '使用工具，让答案有据可查',
    icon: 'tool',
    prompt: '请调用 add 工具计算 18.5 + 23.8，并解释结果。',
  },
  {
    title: '查找长期记忆',
    caption: '找回偏好、知识与业务线索',
    icon: 'memory',
    prompt: '请使用 search_memory 查找以下信息，并注明来源：',
  },
  {
    title: '梳理研究计划',
    caption: '拆解问题，理清下一步',
    icon: 'search',
    prompt: '请为以下问题制定研究计划，区分已知事实和需要外部核验的内容：',
  },
  {
    title: '构思界面',
    caption: '把产品想法变成清晰方案',
    icon: 'edit',
    prompt: '请为以下产品需求设计界面结构和交互方案：',
  },
]
const codingSuggestions = [
  {
    title: '了解项目',
    caption: '阅读结构与开发约定',
    icon: 'folder',
    prompt: '请用 list_files 和 read_file 了解当前项目，阅读开发约定，说明代码结构。',
  },
  {
    title: '查找实现',
    caption: '搜索代码，定位调用关系',
    icon: 'search',
    prompt: '请使用 search_code 定位以下功能的实现，并注明文件和行号：',
  },
  {
    title: '修复问题',
    caption: '先分析，再修改与验证',
    icon: 'edit',
    prompt: '请先阅读相关代码，分析并修复以下问题；修改后运行适合的已启用检查：',
  },
  {
    title: '检查项目',
    caption: '运行测试或构建并解读结果',
    icon: 'code',
    prompt:
      '请查看项目结构，从已启用的 run_checks 预设中选择适当的检查，申请批准后执行并解释实际结果。',
  },
]
const suggestions = computed(() =>
  agentMode.value === 'coding' ? codingSuggestions : generalSuggestions,
)
async function prompt(text: string) {
  usePrompt(text)
  await nextTick()
  composer.value?.focus()
}
function tool(name: string) {
  draft.value = `请使用 ${name} 工具完成以下任务：`
}
function onScroll() {
  if (scroll.value)
    following.value =
      scroll.value.scrollHeight - scroll.value.scrollTop - scroll.value.clientHeight < 80
}
async function toBottom() {
  await nextTick()
  if (scroll.value) scroll.value.scrollTop = scroll.value.scrollHeight
  following.value = true
}
watch(
  () => [events.value.length, output.value, approval.value?.request_id, approval.value?.decision],
  async () => {
    if (following.value) await toBottom()
  },
)
watch(selectedId, () => {
  following.value = true
})
async function copyOutput() {
  try {
    await navigator.clipboard.writeText(output.value)
    notify('回答已复制。')
  } catch {
    notify('当前环境无法写入剪贴板，请选择回答文本复制。', 'error')
  }
}
defineExpose({ focus: () => composer.value?.focus() })
</script>

<template>
  <section v-if="!selectedId" class="welcome-view" aria-label="新任务工作区">
    <div class="welcome-stack">
      <div class="welcome-heading">
        <div class="welcome-title">
          <img src="/brand/slothy-symbol.png" alt="Slothy 品牌标志" />
          <h1>{{ modeLabel }}</h1>
          <span class="preview-badge">LOCAL</span>
        </div>
        <p>
          {{
            agentMode === 'coding'
              ? '读懂项目，修改代码，验证每一步。'
              : '从一个想法开始，让每一步行动清晰可见。'
          }}
        </p>
      </div>
      <div v-if="agentMode === 'coding' && !codingReady" class="coding-start-prompt">
        <span>在左侧选择一个项目，开始编写。</span>
        <button class="text-button" :disabled="!connected" @click="emit('createProject')">
          <AppIcon name="plus" :size="14" />
          创建项目
        </button>
      </div>
      <TaskComposer
        ref="composer"
        v-model="draft"
        :enabled="connected && configured && codingReady && !toolsLoading && !modelBusy"
        :busy="creatingTask"
        :tools="tools"
        :placeholder="
          agentMode === 'coding'
            ? '描述代码任务：阅读项目、修复问题或运行检查…'
            : '描述一个任务，让 Slothy 帮你开始…'
        "
        :reason="reason"
        @send="send"
        @tool="tool"
      />
      <div class="suggestion-grid">
        <button v-for="item in suggestions" :key="item.title" @click="prompt(item.prompt)">
          <AppIcon :name="item.icon" :size="18" />
          <span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.caption }}</small>
          </span>
          <AppIcon name="chevron" :size="13" />
        </button>
      </div>
      <button class="explore-link" @click="section = 'inspiration'">
        探索更多灵感
        <AppIcon name="chevron" :size="14" />
      </button>
      <p v-if="connected && !configured" class="model-setup">
        <AppIcon name="settings" :size="14" />
        文本模型尚未配置
        <button @click="section = 'settings'">查看设置</button>
      </p>
    </div>
    <span class="welcome-footnote">你的工作区。你的工具。你的节奏。</span>
  </section>
  <section v-else class="run-view" :class="{ 'inspector-visible': inspectorOpen }">
    <div class="run-main">
      <header class="run-heading">
        <div class="run-heading-title">
          <h2 :title="selectedTask?.title">{{ selectedTask?.title || '任务执行' }}</h2>
          <RunStatus :status="run?.status || 'idle'" />
        </div>
        <div class="run-controls">
          <span>
            {{ run?.step_count || 0 }} / {{ run?.max_steps || '—' }} 轮
            <span class="middle-dot">·</span>
            {{ run ? formatDuration(run.duration_ms) : '等待执行' }}
          </span>
          <div>
            <button
              v-if="run?.status === 'idle' && !busy"
              class="primary-button small"
              :disabled="!configured"
              @click="control('execute_run')"
            >
              <AppIcon name="play" :size="13" />
              启动执行
            </button>
            <button
              v-if="busy && !run?.cancel_requested && run?.status !== 'cancelled'"
              class="secondary-button small"
              :disabled="controlBusy || run?.interrupt_requested"
              @click="control('interrupt_run')"
            >
              <AppIcon name="pause" :size="13" />
              {{ run?.interrupt_requested ? '正在暂停' : '暂停' }}
            </button>
            <button
              v-if="
                run && ['suspended', 'failed', 'waiting_approval'].includes(run.status) && !busy
              "
              class="primary-button small"
              :disabled="run.status === 'waiting_approval' && !approval?.decision"
              @click="control('resume_run')"
            >
              <AppIcon name="play" :size="13" />
              继续执行
            </button>
            <button
              v-if="run && !['completed', 'failed', 'cancelled'].includes(run.status)"
              class="secondary-button small"
              :disabled="controlBusy || run.cancel_requested"
              @click="control('cancel_run')"
            >
              <AppIcon name="stop" :size="12" />
              {{ run.cancel_requested ? '正在取消' : '取消' }}
            </button>
            <button
              class="icon-button detail-toggle"
              :aria-pressed="inspectorOpen"
              :aria-label="inspectorOpen ? '隐藏任务详情' : '显示任务详情'"
              @click="inspectorOpen = !inspectorOpen"
            >
              <AppIcon name="panel" :size="16" />
            </button>
          </div>
        </div>
      </header>
      <div ref="scroll" class="run-scroll" @scroll.passive="onScroll">
        <div class="run-content">
          <div v-if="loadingTask" class="loading-line" role="status">正在读取任务…</div>
          <article class="user-message">
            <div class="message-overline">任务输入</div>
            <div
              v-if="selectedTask?.agent_mode === 'coding'"
              class="task-workspace-label"
              :title="selectedTask.coding_binding?.workspace_root || ''"
            >
              sloty coding · {{ selectedTask.coding_binding?.workspace_root }}
            </div>
            <p>{{ selectedTask?.goal }}</p>
          </article>
          <article class="agent-message">
            <header class="agent-heading">
              <img src="/brand/slothy-symbol.png" alt="" />
              <strong>Slothy</strong>
              <span v-if="busy" class="working-label">
                <i class="connection-dot online"></i>
                正在处理
              </span>
            </header>
            <RunTimeline :nodes="process" :truncated="truncated" />
            <ApprovalCard
              v-if="approval"
              :approval="approval"
              :busy="approvalBusy"
              @decide="decide"
            />
            <div v-if="output" class="answer-block">
              <p class="answer-text">{{ output }}</p>
              <button
                v-if="!busy"
                class="icon-button copy-answer"
                aria-label="复制回答"
                title="复制回答"
                @click="copyOutput"
              >
                <AppIcon name="copy" :size="15" />
              </button>
            </div>
            <p v-if="run?.error_code && run.status !== 'cancelled'" class="error-inline">
              <AppIcon name="warning" :size="16" />
              执行未完成 · {{ run.error_code }}
            </p>
            <p v-if="run?.status === 'cancelled'" class="stopped-inline">
              <AppIcon name="stop" :size="14" />
              任务已取消。
            </p>
          </article>
        </div>
      </div>
      <button v-if="!following" class="scroll-bottom" aria-label="滚动到最新记录" @click="toBottom">
        <AppIcon name="down" :size="16" />
      </button>
      <div class="run-composer">
        <TaskComposer
          ref="composer"
          v-model="draft"
          compact
          :enabled="connected && configured && codingReady && !toolsLoading && !modelBusy"
          :busy="creatingTask || busy"
          :tools="tools"
          :placeholder="
            agentMode === 'coding'
              ? '描述代码任务：阅读项目、修复问题或运行检查…'
              : '描述一个任务，让 Slothy 帮你开始…'
          "
          :reason="reason"
          @send="send"
          @tool="tool"
        />
      </div>
    </div>
    <RunInspector
      v-if="inspectorOpen"
      :details="details"
      :budget="budget"
      :events="events"
      @close="inspectorOpen = false"
      @logs="section = 'logs'"
    />
  </section>
</template>
