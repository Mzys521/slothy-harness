<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import type { AgentMode } from '../types/desktop'

const props = defineProps<{ mode: AgentMode }>()
const emit = defineEmits<{ change: [AgentMode] }>()
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const label = computed(() => (props.mode === 'coding' ? 'sloty coding' : 'slothy chat'))
const modes: { id: AgentMode; label: string; caption: string; icon: string }[] = [
  { id: 'general', label: 'slothy chat', caption: '对话、计算与长期记忆', icon: 'message' },
  { id: 'coding', label: 'sloty coding', caption: '项目、代码与运行检查', icon: 'code' },
]
function toggle() {
  if (!menu.value || !trigger.value) return
  if (open.value) {
    menu.value.hidePopover()
    return
  }
  const bounds = trigger.value.getBoundingClientRect()
  menu.value.style.left = Math.max(12, Math.min(bounds.left, window.innerWidth - 268)) + 'px'
  menu.value.style.top = bounds.bottom + 8 + 'px'
  menu.value.showPopover()
  menu.value.querySelector<HTMLButtonElement>('button[aria-checked="true"]')?.focus()
}
function onKey(event: KeyboardEvent) {
  if (!menu.value || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const buttons = Array.from(menu.value.querySelectorAll<HTMLButtonElement>('button'))
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const target =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? buttons.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
  buttons[target]?.focus()
}
function choose(mode: AgentMode) {
  menu.value?.hidePopover()
  emit('change', mode)
  trigger.value?.focus()
}
</script>

<template>
  <div class="mode-switcher">
    <button
      ref="trigger"
      class="mode-trigger"
      :aria-label="'切换模式，当前 ' + label"
      :title="label"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="toggle"
    >
      <AppIcon :name="mode === 'coding' ? 'code' : 'message'" :size="22" />
      <span>{{ label }}</span>
      <AppIcon class="mode-chevron" name="down" :size="14" />
    </button>
    <div
      ref="menu"
      popover="auto"
      class="sidebar-popover mode-menu"
      role="menu"
      aria-label="选择工作模式"
      @keydown="onKey"
      @toggle="open = ($event as ToggleEvent).newState === 'open'"
    >
      <button
        v-for="item in modes"
        :key="item.id"
        role="menuitemradio"
        :aria-checked="mode === item.id"
        :class="{ chosen: mode === item.id }"
        @click="choose(item.id)"
      >
        <AppIcon :name="item.icon" :size="20" />
        <span>
          <strong>{{ item.label }}</strong>
          <small>{{ item.caption }}</small>
        </span>
        <AppIcon v-if="mode === item.id" name="check" :size="16" />
      </button>
    </div>
  </div>
</template>
