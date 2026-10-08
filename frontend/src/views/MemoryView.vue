<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import { useWorkspace } from '../stores/workspace'
const emit = defineEmits<{ remember: [] }>()
const { connected, memories, memoryQuery, memoryBusy, memorySearched, searchMemory } =
  useWorkspace()
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <span class="page-eyebrow">MEMORY</span>
        <h1>长期记忆</h1>
        <p>任务完成后才保存对话，也可手动记录偏好与知识。</p>
      </div>
      <button class="primary-button" :disabled="!connected" @click="emit('remember')">
        <AppIcon name="plus" :size="16" />
        保存记忆
      </button>
    </header>
    <form class="search-form memory-search" @submit.prevent="searchMemory">
      <AppIcon name="search" :size="19" />
      <input
        v-model="memoryQuery"
        aria-label="搜索长期记忆"
        placeholder="搜索偏好、知识或业务记录"
        maxlength="4096"
      />
      <button class="secondary-button" :disabled="memoryBusy || !connected || !memoryQuery.trim()">
        {{ memoryBusy ? '检索中…' : '检索记忆' }}
      </button>
    </form>
    <div v-if="memories.length" class="section-caption">
      <span>检索结果</span>
      <span>{{ memories.length }} 条</span>
    </div>
    <article v-for="memory in memories" :key="memory.id" class="memory-card">
      <header>
        <AppIcon name="memory" :size="16" />
        <strong>{{ memory.source === 'completed_run' ? '已完成任务' : memory.source || '记忆' }}</strong>
        <span class="neutral-badge">相关度 {{ memory.score.toFixed(3) }}</span>
      </header>
      <p>{{ memory.text }}</p>
      <code>{{ memory.id }}</code>
    </article>
    <div v-if="!memories.length" class="page-empty">
      <span class="empty-symbol warm"><AppIcon name="memory" :size="27" /></span>
      <h2>{{ memorySearched ? '没有找到相关记忆' : '让下一次任务更懂你' }}</h2>
      <p>
        {{
          memorySearched
            ? '试试其他关键词，或保存一条新的记忆。'
            : '输入关键词，查找你的偏好、知识和业务线索。'
        }}
      </p>
    </div>
  </section>
</template>
