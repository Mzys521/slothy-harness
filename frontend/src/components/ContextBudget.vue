<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { formatDuration, formatTokens } from '../services/eventProjection'
import type { BudgetView, RunView } from '../types/desktop'
defineProps<{
  budget: BudgetView
  run: RunView | null
  tokens: number | null
  model: string | null
  configured: boolean
}>()
</script>

<template>
  <footer class="status-bar" aria-label="运行预算与状态">
    <div class="context-status">
      <AppIcon name="memory" :size="12" />
      <span>Context</span>
      <div class="budget-segments">
        <span
          v-for="(segment, index) in budget.segments"
          :key="segment.name"
          class="budget-segment"
          :title="`${segment.name}：${segment.used === null ? '未采样' : formatTokens(segment.used)} / ${formatTokens(segment.limit)} tokens${segment.reserved ? '（预留）' : ''}`"
        >
          <span class="segment-name-full">{{ segment.name }}</span>
          <span class="segment-name-short">{{ segment.label }}</span>
          <span class="budget-track" :class="`layer-${index}`">
            <i
              :style="{
                width: `${segment.used === null || !segment.limit ? 0 : Math.min(100, (segment.used / segment.limit) * 100)}%`,
              }"
            ></i>
          </span>
        </span>
      </div>
      <span class="budget-usage">
        {{
          budget.used === null
            ? '未采样'
            : `${formatTokens(budget.used)} / ${formatTokens(budget.limit)}`
        }}
      </span>
    </div>
    <div class="runtime-status">
      <span class="status-duration">
        <AppIcon name="clock" :size="12" />
        {{ run ? formatDuration(run.duration_ms) : '—' }}
      </span>
      <span>{{ tokens === null ? '— tokens' : `${formatTokens(tokens)} tokens` }}</span>
      <span class="status-model" :title="model || '尚未配置文本模型'">
        <i class="connection-dot" :class="{ online: configured }"></i>
        {{ model || '未配置模型' }}
      </span>
    </div>
  </footer>
</template>
