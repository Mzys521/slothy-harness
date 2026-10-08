<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkspace } from '../stores/workspace'
import type { ModelProviderSettings } from '../types/desktop'

const { workspace, connected, creatingTask, modelBusy, section, selectModel, report } =
  useWorkspace()
const menu = ref<HTMLElement | null>(null),
  trigger = ref<HTMLButtonElement | null>(null),
  open = ref(false)
const configured = computed(
  () => workspace.value?.status.model_settings?.providers.filter((item) => item.configured) || [],
)
const selection = computed(() => workspace.value?.status.model_settings?.selection)
const label = computed(() => workspace.value?.status.model.name || '选择文本模型')
function toggle() {
  if (!menu.value || !trigger.value) return
  if (open.value) {
    menu.value.hidePopover()
    return
  }
  const bounds = trigger.value.getBoundingClientRect()
  menu.value.style.left = Math.max(10, Math.min(bounds.right - 300, innerWidth - 310)) + 'px'
  menu.value.style.top = 'auto'
  menu.value.style.bottom = Math.max(10, innerHeight - bounds.top + 8) + 'px'
  menu.value.showPopover()
  menu.value.querySelector<HTMLButtonElement>('button[aria-checked="true"], button')?.focus()
}
function onKey(event: KeyboardEvent) {
  if (!menu.value || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const buttons = Array.from(
    menu.value.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'),
  )
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const target =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? buttons.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
  buttons[target]?.focus()
}
async function choose(provider: ModelProviderSettings, model: string) {
  menu.value?.hidePopover()
  trigger.value?.focus()
  try {
    await selectModel({ provider_id: provider.id, endpoint_id: provider.endpoint_id, model })
  } catch (error) {
    report(error)
  }
}
function settings() {
  menu.value?.hidePopover()
  section.value = 'settings'
}
</script>

<template>
  <div class="model-picker">
    <button
      ref="trigger"
      type="button"
      class="composer-model model-trigger"
      :title="label"
      :aria-label="'切换模型，当前 ' + label"
      :disabled="!connected || modelBusy || creatingTask"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="toggle"
    >
      <span>{{ modelBusy ? '正在切换…' : label }}</span>
      <AppIcon name="down" :size="12" />
    </button>
    <div
      ref="menu"
      popover="auto"
      class="model-menu"
      role="menu"
      aria-label="选择模型"
      @toggle="open = ($event as ToggleEvent).newState === 'open'"
      @keydown="onKey"
    >
      <div class="menu-caption">新任务使用的模型</div>
      <div class="model-menu-list">
        <section v-for="provider in configured" :key="provider.id">
          <h3>{{ provider.name }}</h3>
          <button
            v-for="item in provider.models"
            :key="item"
            role="menuitemradio"
            :aria-checked="
              selection?.provider_id === provider.id &&
              selection?.endpoint_id === provider.endpoint_id &&
              selection?.model === item
            "
            :disabled="modelBusy"
            @click="choose(provider, item)"
          >
            <span>{{ item }}</span>
            <AppIcon
              v-if="selection?.provider_id === provider.id && selection?.model === item"
              name="check"
              :size="14"
            />
          </button>
        </section>
        <p v-if="!configured.length">在设置中添加提供商和 API Key，即可切换模型。</p>
      </div>
      <button type="button" class="model-menu-settings" role="menuitem" @click="settings">
        <AppIcon name="settings" :size="15" />
        管理模型提供商
        <AppIcon name="chevron" :size="12" />
      </button>
    </div>
  </div>
</template>
