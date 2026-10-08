<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import ModelPicker from './ModelPicker.vue'
import type { ToolInfo } from '../types/desktop'
const props = defineProps<{
  modelValue: string
  enabled: boolean
  busy: boolean
  tools: ToolInfo[]
  compact?: boolean
  reason?: string
  placeholder?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [string]; send: []; tool: [string] }>()
const input = ref<HTMLTextAreaElement | null>(null)
const toolMenu = ref(false)
const menuDismissed = ref(false)
const menuOpen = computed(
  () => toolMenu.value || (props.modelValue.startsWith('/') && !menuDismissed.value),
)
const matches = computed(() =>
  props.tools.filter(
    (tool) =>
      !props.modelValue.startsWith('/') ||
      tool.name.includes(props.modelValue.slice(1).split(' ')[0] || ''),
  ),
)
function resize() {
  if (!input.value) return
  input.value.style.height = 'auto'
  input.value.style.height =
    Math.min(200, Math.max(props.compact ? 46 : 72, input.value.scrollHeight)) + 'px'
}
watch(
  () => props.modelValue,
  async () => {
    menuDismissed.value = false
    await nextTick()
    resize()
  },
)
onMounted(resize)
function submit() {
  if (props.enabled && !props.busy && props.modelValue.trim()) emit('send')
}
function toggleTools() {
  const opening = !menuOpen.value
  toolMenu.value = opening
  menuDismissed.value = !opening
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    toolMenu.value = false
    menuDismissed.value = true
    event.preventDefault()
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault()
    submit()
  }
}
function selectTool(name: string) {
  toolMenu.value = false
  emit('tool', name)
  void nextTick(() => input.value?.focus())
}
defineExpose({ focus: () => input.value?.focus() })
</script>

<template>
  <div class="composer-wrap">
    <div v-if="menuOpen" class="composer-menu" aria-label="已注册工具">
      <div class="menu-caption">选择一个工具</div>
      <button v-for="tool in matches" :key="tool.name" @click="selectTool(tool.name)">
        <AppIcon name="tool" :size="16" />
        <span>
          <strong>{{ tool.name }}</strong>
          <small>{{ tool.description }}</small>
        </span>
        <AppIcon name="chevron" :size="13" />
      </button>
      <p v-if="!matches.length">没有匹配的已注册工具。</p>
    </div>
    <form class="task-composer" :class="{ compact }" @submit.prevent="submit">
      <textarea
        ref="input"
        :value="modelValue"
        aria-label="任务输入"
        :placeholder="placeholder || '描述一个任务，让 Slothy 帮你开始…'"
        maxlength="100000"
        rows="2"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
        @keydown="onKey"
      />
      <div class="composer-toolbar">
        <button
          type="button"
          class="icon-button tool-trigger"
          aria-label="添加工具"
          :aria-expanded="menuOpen"
          title="添加已注册工具，也可以输入 /"
          @click="toggleTools"
        >
          <AppIcon name="plus" :size="21" />
        </button>
        <ModelPicker />
        <button
          class="send-button"
          aria-label="发送任务"
          :disabled="!enabled || busy || !modelValue.trim()"
          :title="reason || (busy ? '当前任务正在执行' : '发送任务')"
        >
          <AppIcon :name="busy ? 'clock' : 'arrow'" :size="19" />
        </button>
      </div>
    </form>
    <div class="composer-caption">
      <span>
        {{
          reason || (busy ? '任务正在执行，可以查看状态或暂停' : 'Enter 发送 · Shift + Enter 换行')
        }}
      </span>
      <span v-if="!compact">输入 / 选择工具</span>
    </div>
  </div>
</template>
