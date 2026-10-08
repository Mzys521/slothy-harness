<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import type { Approval } from '../types/desktop'
defineProps<{ approval: Approval; busy: boolean }>()
const emit = defineEmits<{ decide: [boolean] }>()
</script>

<template>
  <section class="approval-card" aria-label="工具审批">
    <div class="approval-heading">
      <AppIcon name="shield" :size="19" />
      <h3>需要你的决定</h3>
      <span>第 {{ approval.attempt }} 次尝试</span>
    </div>
    <p>
      <strong>{{ approval.tool_name }}</strong>
      · {{ approval.reason }}
    </p>
    <details>
      <summary>查看本次请求参数</summary>
      <pre>{{ JSON.stringify(approval.arguments, null, 2) }}</pre>
    </details>
    <div v-if="!approval.decision" class="approval-actions">
      <button class="secondary-button" :disabled="busy" @click="emit('decide', false)">
        拒绝本次尝试
      </button>
      <button class="primary-button" :disabled="busy" @click="emit('decide', true)">
        批准本次尝试
      </button>
    </div>
    <p v-else class="approval-result">
      {{ approval.decision === 'approved' ? '已批准' : '已拒绝' }}。点击“继续执行”恢复任务。
    </p>
  </section>
</template>
