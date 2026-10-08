<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { formatTokens } from '../services/eventProjection'
import type { BudgetView, RunDetails, RunEvent } from '../types/desktop'
defineProps<{ details: RunDetails | null; budget: BudgetView; events: RunEvent[] }>()
const emit = defineEmits<{ close: []; logs: [] }>()
const tab = ref<'state' | 'events'>('state')
</script>

<template>
  <aside class="run-inspector" aria-label="任务详情">
    <header class="inspector-heading">
      <strong>任务详情</strong>
      <button class="icon-button" aria-label="收起任务详情" @click="emit('close')">
        <AppIcon name="panel" :size="16" />
      </button>
    </header>
    <nav class="inspector-tabs" aria-label="任务详情分类">
      <button
        :aria-pressed="tab === 'state'"
        :class="{ active: tab === 'state' }"
        @click="tab = 'state'"
      >
        任务状态
      </button>
      <button
        :aria-pressed="tab === 'events'"
        :class="{ active: tab === 'events' }"
        @click="tab = 'events'"
      >
        事件
        <span>{{ events.length }}</span>
      </button>
    </nav>
    <div class="inspector-scroll">
      <template v-if="tab === 'state' && details">
        <section class="inspector-section">
          <div class="inspector-section-title">
            <AppIcon name="home" :size="15" />
            <h3>目标</h3>
          </div>
          <p>{{ details.task_state.goal }}</p>
        </section>
        <section
          v-for="group in [
            { key: 'plan' as const, title: '执行计划', empty: '尚无结构化计划' },
            { key: 'completed_steps' as const, title: '已完成步骤', empty: '尚无已完成步骤记录' },
            { key: 'todo_list' as const, title: '待办事项', empty: '尚无待办事项' },
          ]"
          :key="group.key"
          class="inspector-section"
        >
          <div class="inspector-section-title">
            <h3>{{ group.title }}</h3>
            <span>{{ details.task_state[group.key].length }}</span>
          </div>
          <ul v-if="details.task_state[group.key].length" class="state-items">
            <li v-for="(item, index) in details.task_state[group.key]" :key="index">
              <AppIcon :name="group.key === 'completed_steps' ? 'check' : 'chevron'" :size="13" />
              {{ item }}
            </li>
          </ul>
          <p v-else class="subtle-text">{{ group.empty }}</p>
        </section>
        <section class="inspector-section task-state-card">
          <details>
            <summary>
              <span>Task State</span>
              <code>JSON</code>
            </summary>
            <pre>{{ JSON.stringify(details.task_state, null, 2) }}</pre>
          </details>
        </section>
        <section class="inspector-section inspector-budget">
          <div class="inspector-section-title">
            <AppIcon name="memory" :size="15" />
            <h3>上下文预算</h3>
          </div>
          <div
            v-for="(segment, index) in budget.segments"
            :key="segment.name"
            class="inspector-budget-row"
          >
            <div>
              <span>{{ segment.label }}</span>
              <code>
                {{ segment.used === null ? '未采样' : formatTokens(segment.used) }} /
                {{ formatTokens(segment.limit) }}
              </code>
            </div>
            <span class="budget-track" :class="`layer-${index}`">
              <i
                :style="{
                  width: `${segment.used === null || !segment.limit ? 0 : Math.min(100, (segment.used / segment.limit) * 100)}%`,
                }"
              ></i>
            </span>
          </div>
          <p class="subtle-text">输入为计数器估算；输出为预留预算。</p>
        </section>
      </template>
      <template v-else-if="tab === 'events'">
        <div
          class="inspector-event"
          v-for="event in events.slice(-60).toReversed()"
          :key="event.cursor"
        >
          <span>#{{ event.sequence }}</span>
          <code>{{ event.event_type }}</code>
          <small>Step {{ event.step_number ?? '—' }}</small>
        </div>
        <p v-if="!events.length" class="inline-note">还没有事件记录。</p>
        <button class="text-button inspector-log-link" @click="emit('logs')">
          查看完整运行日志
          <AppIcon name="chevron" :size="14" />
        </button>
      </template>
      <p v-else class="inline-note">正在读取任务详情…</p>
    </div>
  </aside>
</template>
