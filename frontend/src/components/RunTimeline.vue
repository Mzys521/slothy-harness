<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { formatDuration } from '../services/eventProjection'
import type { ProcessNode } from '../types/desktop'
defineProps<{ nodes: ProcessNode[]; truncated: boolean }>()
</script>

<template>
  <details class="process-disclosure" open>
    <summary>
      <AppIcon name="down" :size="14" />
      <span>执行过程</span>
      <span class="subtle-text">{{ nodes.length }} 个节点</span>
    </summary>
    <p v-if="truncated" class="inline-note">早期事件已超出缓存，当前显示可读取的记录。</p>
    <ol class="timeline">
      <li v-for="node in nodes" :key="node.id" class="process-node" :class="node.status">
        <details>
          <summary>
            <span class="process-icon">
              <AppIcon
                :name="
                  node.status === 'success'
                    ? 'check'
                    : node.status === 'failed'
                      ? 'warning'
                      : node.status === 'waiting' || node.status === 'stopped'
                        ? 'clock'
                        : node.kind === 'tool'
                          ? 'tool'
                          : 'sparkles'
                "
                :size="15"
              />
            </span>
            <span class="process-title">{{ node.name }}</span>
            <span class="process-label">{{ node.label }}</span>
            <span v-if="node.retries" class="retry-label">重试 {{ node.retries }} 次</span>
            <span class="process-time">
              {{ node.duration === null ? '—' : formatDuration(node.duration) }}
            </span>
            <AppIcon name="down" :size="12" />
          </summary>
          <div class="process-detail">
            <p>{{ node.detail }}</p>
            <div class="process-meta">
              <span>Step {{ node.step ?? '—' }}</span>
              <span>Generation {{ node.generation }}</span>
              <code v-if="node.callId">{{ node.callId }}</code>
            </div>
            <div v-if="node.progress" class="process-progress">
              {{ node.progress.completed }} / {{ node.progress.total ?? '—' }}
              <progress
                v-if="node.progress.total && node.progress.total > 0"
                :value="node.progress.completed"
                :max="node.progress.total"
              ></progress>
            </div>
          </div>
        </details>
      </li>
    </ol>
    <p v-if="!nodes.length" class="inline-note">运行开始后，模型与工具事件会显示在这里。</p>
  </details>
</template>
