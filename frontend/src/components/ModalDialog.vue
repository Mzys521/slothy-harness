<script setup lang="ts">
import { nextTick, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ open: boolean; title: string; busy?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const element = ref<HTMLDialogElement | null>(null)
const titleId = useId()
watch(
  () => props.open,
  async (open) => {
    await nextTick()
    if (open && !element.value?.open) element.value?.showModal()
    else if (!open && element.value?.open) element.value.close()
  },
  { immediate: true },
)
function close() {
  if (!props.busy) emit('close')
}
function backdrop(event: MouseEvent) {
  if (event.target !== element.value) return
  const bounds = element.value?.getBoundingClientRect()
  if (
    bounds &&
    (event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom)
  )
    close()
}
</script>

<template>
  <dialog
    ref="element"
    class="modal-dialog"
    :aria-labelledby="titleId"
    @cancel.prevent="close"
    @click="backdrop"
  >
    <header class="modal-heading">
      <h2 :id="titleId">{{ title }}</h2>
      <button class="icon-button" aria-label="关闭对话框" :disabled="busy" @click="close">
        <AppIcon name="close" />
      </button>
    </header>
    <div class="modal-body"><slot /></div>
  </dialog>
</template>
