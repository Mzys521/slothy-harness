<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import { statusLabels } from '../services/eventProjection'
import { useWorkspace } from '../stores/workspace'
const { events, selectedTask, truncated, section, exportLogs } = useWorkspace()
</script>

<template>
  <section class="page-view logs-view">
    <header class="page-heading">
      <div>
        <span class="page-eyebrow">OBSERVABILITY</span>
        <h1>运行日志</h1>
        <p>{{ selectedTask?.title || '选择一个任务，查看它真实发生的每一步。' }}</p>
      </div>
      <button class="secondary-button" :disabled="!events.length" @click="exportLogs">
        <AppIcon name="download" :size="15" />
        导出日志
      </button>
    </header>
    <div v-if="selectedTask" class="log-task-context">
      <AppIcon name="logs" :size="16" />
      <span>{{ events.length }} 条事件</span>
      <button class="text-button" @click="section = 'harness'">
        返回任务
        <AppIcon name="chevron" :size="14" />
      </button>
    </div>
    <p v-if="truncated" class="inline-note">早期事件已超出缓存范围，导出仅包含当前可读取的事件。</p>
    <div v-if="events.length" class="events-table">
      <div class="event-table-heading">
        <span>序号</span>
        <span>事件</span>
        <span>步骤</span>
        <span>状态</span>
      </div>
      <details v-for="event in events" :key="event.cursor">
        <summary>
          <code>#{{ event.sequence }}</code>
          <code class="event-name" :title="event.event_type">{{ event.event_type }}</code>
          <span>{{ event.step_number ?? '—' }}</span>
          <span>{{ statusLabels[event.status] || event.status }}</span>
        </summary>
        <div class="event-body">
          <div>Generation {{ event.generation }} · Cursor {{ event.cursor }}</div>
          <pre>{{ JSON.stringify(event.payload, null, 2) }}</pre>
        </div>
      </details>
    </div>
    <div v-else class="page-empty">
      <AppIcon name="logs" :size="34" />
      <h2>{{ selectedTask ? '还没有事件记录' : '先选择一个任务' }}</h2>
      <p>
        {{
          selectedTask ? '任务启动后，事件会自动显示在这里。' : '从侧栏打开任务，再进入运行日志。'
        }}
      </p>
    </div>
  </section>
</template>
