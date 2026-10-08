<script setup lang="ts">
import { ref, watch, useId } from 'vue'
import AppIcon from './AppIcon.vue'
import type { Project, TaskRecord } from '../types/desktop'
import { statusLabels } from '../services/eventProjection'

const props = defineProps<{
  project: Project
  tasks: TaskRecord[]
  active: boolean
  selectedId: string | null
  connected: boolean
}>()
const emit = defineEmits<{
  choose: [string]
  select: [TaskRecord]
  newTask: [string]
  edit: [Project]
  pin: [Project]
}>()
const listId = useId()
const key = 'slothy-project-expanded:' + props.project.id
let savedExpanded = true
try {
  savedExpanded = localStorage.getItem(key) !== 'false'
} catch {
  /* UI 偏好不可用时展开 */
}
const expanded = ref(savedExpanded)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
watch(expanded, (value) => {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    /* 不影响项目操作 */
  }
})
watch(
  () => props.selectedId,
  (value) => {
    if (props.tasks.some((task) => task.run_id === value)) expanded.value = true
  },
)
function toggleProject() {
  expanded.value = !expanded.value
  emit('choose', props.project.id)
}
function details() {
  if (!menu.value || !trigger.value) return
  if (menuOpen.value) {
    menu.value.hidePopover()
    return
  }
  const bounds = trigger.value.getBoundingClientRect()
  const sidebarRight =
    trigger.value.closest('.sidebar')?.getBoundingClientRect().right || bounds.right
  const width = Math.min(360, window.innerWidth - 24)
  menu.value.style.width = width + 'px'
  menu.value.style.left =
    Math.max(12, Math.min(sidebarRight + 10, window.innerWidth - width - 12)) + 'px'
  menu.value.style.top = Math.max(12, Math.min(bounds.top - 8, window.innerHeight - 260)) + 'px'
  menu.value.showPopover()
}
function edit() {
  menu.value?.hidePopover()
  emit('edit', props.project)
}
function pin() {
  menu.value?.hidePopover()
  emit('pin', props.project)
}
function newTask() {
  expanded.value = true
  emit('newTask', props.project.id)
}
</script>

<template>
  <section class="project-group" :data-project-id="project.id" :aria-label="'项目 ' + project.name">
    <div class="project-heading" :class="{ active }">
      <button
        class="project-toggle"
        :aria-label="(expanded ? '折叠' : '展开') + '项目 ' + project.name"
        :aria-expanded="expanded"
        :aria-controls="listId"
        :title="project.name"
        @click="toggleProject"
      >
        <AppIcon name="folder" :size="20" />
        <span>{{ project.name }}</span>
        <AppIcon class="project-chevron" name="down" :size="12" />
      </button>
      <button
        ref="trigger"
        class="icon-button project-detail-trigger"
        :aria-label="project.name + ' 项目详情'"
        :aria-expanded="menuOpen"
        aria-haspopup="dialog"
        @click="details"
      >
        <AppIcon name="more" :size="18" />
      </button>
      <button
        class="icon-button project-new-task"
        :aria-label="'在 ' + project.name + ' 中新建任务'"
        :disabled="!connected"
        @click="newTask"
      >
        <AppIcon name="compose" :size="17" />
      </button>
    </div>
    <div v-if="expanded" :id="listId" class="project-task-list">
      <button
        v-for="task in tasks"
        :key="task.run_id"
        class="sidebar-task"
        :class="{ active: task.run_id === selectedId }"
        :title="task.title"
        :aria-current="task.run_id === selectedId ? 'page' : undefined"
        @click="emit('select', task)"
      >
        <span>{{ task.title }}</span>
        <i
          v-if="['running', 'thinking', 'executing_tool'].includes(task.run?.status || '')"
          class="task-running-dot"
        />
        <span class="sr-only">
          {{ task.available === false ? '快照不可用' : statusLabels[task.run?.status || 'idle'] }}
        </span>
      </button>
      <p v-if="!tasks.length" class="project-empty">还没有任务</p>
    </div>
    <div
      ref="menu"
      popover="auto"
      class="sidebar-popover project-details"
      role="dialog"
      :aria-label="project.name + ' 项目详情菜单'"
      @toggle="menuOpen = ($event as ToggleEvent).newState === 'open'"
    >
      <div class="project-details-title">
        <AppIcon name="folder" :size="20" />
        <strong>{{ project.name }}</strong>
        <button
          class="icon-button"
          :aria-label="(project.pinned ? '取消置顶' : '置顶') + '项目 ' + project.name"
          :aria-pressed="!!project.pinned"
          :disabled="!connected"
          @click="pin"
        >
          <AppIcon name="pin" :size="18" />
        </button>
      </div>
      <div class="project-details-count">
        <AppIcon name="message" :size="20" />
        <span>{{ tasks.length }} 个任务</span>
      </div>
      <div class="project-details-environment">
        <a
          v-if="project.repository"
          :href="project.repository.url"
          target="_blank"
          rel="noreferrer"
        >
          <AppIcon name="repository" :size="20" />
          <span>{{ project.repository.label }}</span>
        </a>
        <div>
          <AppIcon name="folder" :size="20" />
          <span>{{ project.workspace_root || '尚未添加源文件夹' }}</span>
        </div>
      </div>
      <button class="project-edit-button" :disabled="!connected" @click="edit">
        <AppIcon name="settings" :size="20" />
        <span>编辑项目</span>
      </button>
    </div>
  </section>
</template>
