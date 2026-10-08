<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { statusLabels } from '../services/eventProjection'
defineProps<{ status: string }>()
</script>

<template>
  <span class="run-badge" :class="status">
    <AppIcon
      :name="
        status === 'completed'
          ? 'check'
          : status === 'failed'
            ? 'warning'
            : status === 'cancelled'
              ? 'stop'
              : 'clock'
      "
      :size="13"
    />
    {{ statusLabels[status] || status }}
  </span>
</template>
