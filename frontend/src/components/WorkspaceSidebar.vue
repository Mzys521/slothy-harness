<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import ModeSwitcher from './ModeSwitcher.vue'
import ProjectGroup from './ProjectGroup.vue'
import type { AgentMode, Project, Section, TaskRecord } from '../types/desktop'
const props = defineProps<{
  collapsed: boolean
  section: Section
  connected: boolean
  mode: AgentMode
  projects: Project[]
  tasks: TaskRecord[]
  selectedId: string | null
  projectId: string | null
  user: string
}>()
const emit = defineEmits<{
  toggle: []
  mode: [AgentMode]
  newTask: []
  navigate: [Section]
  project: [string]
  createProject: []
  editProject: [Project]
  pinProject: [Project]
  projectTask: [string]
  select: [TaskRecord]
  search: []
}>()
const projectsOpen = ref(true)
const navigation: { id: Section; label: string; icon: string }[] = [
  { id: 'harness', label: '工作台', icon: 'home' },
  { id: 'tools', label: '工具链', icon: 'tool' },
  { id: 'memory', label: '长期记忆', icon: 'memory' },
  { id: 'inspiration', label: '灵感库', icon: 'sparkles' },
  { id: 'logs', label: '运行日志', icon: 'logs' },
  { id: 'schedules', label: '定时任务', icon: 'clock' },
]
const projects = computed(() =>
  [...props.projects].sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned)),
)
const projectTasks = (id: string) => props.tasks.filter((task) => task.project_id === id)
const ungrouped = computed(() =>
  props.tasks.filter((task) => !props.projects.some((project) => project.id === task.project_id)),
)
const initials = computed(() => props.user.slice(0, 1).toUpperCase() || 'S')
</script>

<template>
  <aside class="sidebar" :class="{ collapsed, coding: mode === 'coding' }" aria-label="工作区导航">
    <div class="sidebar-top">
      <ModeSwitcher :mode="mode" @change="emit('mode', $event)" />
      <button
        class="icon-button sidebar-toggle"
        :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
        :title="collapsed ? '展开侧栏' : '折叠侧栏'"
        @click="emit('toggle')"
      >
        <AppIcon name="panel" :size="17" />
      </button>
    </div>
    <button
      class="new-task-button"
      aria-label="新建任务"
      title="新建任务 · Ctrl K"
      aria-keyshortcuts="Control+K"
      @click="emit('newTask')"
    >
      <AppIcon name="plus" :size="18" />
      <span>新建任务</span>
      <kbd>Ctrl K</kbd>
    </button>
    <button
      class="sidebar-search"
      aria-label="搜索任务"
      title="搜索任务 · Ctrl P"
      @click="emit('search')"
    >
      <AppIcon name="search" :size="17" />
      <span>搜索任务</span>
      <kbd>Ctrl P</kbd>
    </button>
    <nav class="primary-nav" aria-label="功能导航">
      <button
        v-for="item in navigation"
        :key="item.id"
        :class="{ active: section === item.id }"
        :aria-current="section === item.id ? 'page' : undefined"
        :title="item.label"
        @click="emit('navigate', item.id)"
      >
        <AppIcon :name="item.icon" :size="17" />
        <span>{{ item.label }}</span>
      </button>
    </nav>
    <div class="sidebar-scroll">
      <section v-if="mode === 'coding'" class="coding-projects" aria-label="项目环境">
        <div class="sidebar-group-heading">
          <button
            class="project-section-toggle"
            :aria-expanded="projectsOpen"
            aria-controls="coding-projects"
            @click="projectsOpen = !projectsOpen"
          >
            <span>项目</span>
            <AppIcon name="down" :size="13" :class="{ rotated: !projectsOpen }" />
          </button>
          <button
            class="icon-button"
            aria-label="创建项目"
            title="创建项目"
            :disabled="!connected"
            @click="emit('createProject')"
          >
            <AppIcon name="plus" :size="19" />
          </button>
        </div>
        <div v-if="projectsOpen" id="coding-projects">
          <ProjectGroup
            v-for="project in projects"
            :key="project.id"
            :project="project"
            :tasks="projectTasks(project.id)"
            :active="projectId === project.id"
            :selected-id="selectedId"
            :connected="connected"
            @choose="emit('project', $event)"
            @select="emit('select', $event)"
            @new-task="emit('projectTask', $event)"
            @edit="emit('editProject', $event)"
            @pin="emit('pinProject', $event)"
          />
          <button
            v-if="!projects.length"
            class="sidebar-empty create-first-project"
            :disabled="!connected"
            @click="emit('createProject')"
          >
            <AppIcon name="folder" :size="24" />
            <span>创建项目，添加源文件夹</span>
          </button>
        </div>
      </section>
      <section
        v-if="mode === 'general' || ungrouped.length"
        class="sidebar-history"
        :aria-label="mode === 'general' ? 'Chat 任务' : '未分组任务'"
      >
        <div class="sidebar-group-heading">
          {{ mode === 'general' ? '最近任务' : '未分组任务' }}
        </div>
        <button
          v-for="task in mode === 'general' ? tasks : ungrouped"
          :key="task.run_id"
          class="sidebar-task"
          :class="{ active: task.run_id === selectedId }"
          :title="task.title"
          :aria-current="task.run_id === selectedId ? 'page' : undefined"
          @click="emit('select', task)"
        >
          <AppIcon name="message" :size="16" />
          <span>{{ task.title }}</span>
          <i
            v-if="['running', 'thinking', 'executing_tool'].includes(task.run?.status || '')"
            class="task-running-dot"
          />
        </button>
        <p v-if="mode === 'general' && !tasks.length" class="sidebar-empty">
          从一个问题开始，任务会保存在这里。
        </p>
      </section>
    </div>
    <footer class="sidebar-footer">
      <button
        class="settings-nav"
        :class="{ active: section === 'settings' }"
        title="设置"
        @click="emit('navigate', 'settings')"
      >
        <AppIcon name="settings" :size="18" />
        <span>设置</span>
      </button>
      <div class="user-row">
        <div class="user-avatar">{{ initials }}</div>
        <div class="user-details">
          <strong>{{ user }}</strong>
          <span>
            <i class="connection-dot" :class="{ online: connected }" />
            {{ connected ? '本地服务已连接' : '本地服务未连接' }}
          </span>
        </div>
      </div>
    </footer>
  </aside>
</template>
