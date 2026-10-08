<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import { useWorkspace } from '../stores/workspace'
const emit = defineEmits<{ save: []; prompt: [string] }>()
const { workspace, connected } = useWorkspace()
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <span class="page-eyebrow">IDEAS TO ACTION</span>
        <h1>灵感库</h1>
        <p>一个好问题，就是下一次行动的起点。</p>
      </div>
      <button class="primary-button" :disabled="!connected" @click="emit('save')">
        <AppIcon name="plus" :size="16" />
        保存灵感
      </button>
    </header>
    <div class="inspiration-grid">
      <button
        v-for="(item, index) in workspace?.inspirations || []"
        :key="item.id"
        class="inspiration-card"
        @click="emit('prompt', item.prompt)"
      >
        <span class="inspiration-top">
          <AppIcon name="sparkles" :size="22" />
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
        </span>
        <h2>{{ item.title }}</h2>
        <p>{{ item.prompt }}</p>
        <span class="inspiration-action">
          使用这个灵感
          <AppIcon name="chevron" :size="14" />
        </span>
      </button>
    </div>
    <div v-if="!workspace?.inspirations.length" class="page-empty">
      <AppIcon name="sparkles" :size="34" />
      <h2>留住一个想法</h2>
      <p>保存常用提示，下次从这里开始。</p>
    </div>
    <p class="page-footnote">灵感是任务提示模板，点击后填入草稿，发送时才会执行。</p>
  </section>
</template>
