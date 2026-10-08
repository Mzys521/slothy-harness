<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
const emit = defineEmits<{ newTask: [] }>()
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <span class="page-eyebrow">SCHEDULES</span>
        <h1>定时任务</h1>
        <p>让行动发生在合适的时间。</p>
      </div>
    </header>
    <div class="page-empty schedule-empty">
      <span class="empty-symbol warm"><AppIcon name="clock" :size="28" /></span>
      <h2>按时开始，从容完成。</h2>
      <span class="neutral-badge">尚未接入调度服务</span>
      <p>当前可以创建任务并手动运行。定时执行将在调度服务接入后提供。</p>
      <button class="secondary-button" @click="emit('newTask')">
        <AppIcon name="plus" :size="15" />
        新建任务
      </button>
    </div>
  </section>
</template>
