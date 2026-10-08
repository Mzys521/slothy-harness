<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import ModalDialog from './ModalDialog.vue'
import { request } from '../services/bridge'
import { useWorkspace } from '../stores/workspace'
import type { Project, ProjectDirectory } from '../types/desktop'
const props = defineProps<{ open: boolean; project: Project | null }>()
const emit = defineEmits<{ close: [] }>()
const { connected, saveProject } = useWorkspace()
const name = ref('')
const directory = ref<ProjectDirectory | null>(null)
const manual = ref(false)
const path = ref('')
const pathInput = ref<HTMLInputElement | null>(null)
const choosing = ref(false),
  validating = ref(false),
  saving = ref(false),
  error = ref('')
const busy = computed(() => choosing.value || validating.value || saving.value)
watch(
  () => props.open,
  (open) => {
    if (!open) return
    name.value = props.project?.name || ''
    directory.value = props.project?.workspace_root
      ? { workspace_root: props.project.workspace_root, repository: props.project.repository }
      : null
    manual.value = false
    path.value = ''
    error.value = ''
  },
)
async function chooseFolder() {
  if (busy.value) return
  choosing.value = true
  error.value = ''
  try {
    const result = await request('choose_project_directory', {})
    if (result.directory) {
      directory.value = result.directory
      manual.value = false
    } else if (!result.available) {
      manual.value = true
      await nextTick()
      pathInput.value?.focus()
    }
  } catch (caught) {
    manual.value = true
    error.value = caught instanceof Error ? caught.message : '请选择源文件夹，或填写完整路径。'
    await nextTick()
    pathInput.value?.focus()
  } finally {
    choosing.value = false
  }
}
async function attachFolder() {
  if (busy.value || !path.value.trim()) return
  validating.value = true
  error.value = ''
  try {
    directory.value = await request('inspect_project_directory', {
      workspace_root: path.value.trim(),
    })
    manual.value = false
    path.value = ''
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '无法添加源文件夹。'
  } finally {
    validating.value = false
  }
}
async function save() {
  if (busy.value || !name.value.trim() || !directory.value) return
  saving.value = true
  error.value = ''
  try {
    await saveProject(
      { name: name.value.trim(), workspace_root: directory.value.workspace_root },
      props.project,
    )
    emit('close')
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '项目保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <ModalDialog
    :open="open"
    :title="project ? '编辑项目' : '创建项目'"
    :busy="busy"
    class="project-dialog"
    @close="emit('close')"
  >
    <form class="project-form" @submit.prevent="save">
      <label class="project-name-field">
        <AppIcon name="folder" :size="23" />
        <input
          v-model="name"
          aria-label="项目名称"
          placeholder="项目名称"
          maxlength="80"
          required
          autofocus
          :disabled="busy"
        />
      </label>
      <h3>源文件夹</h3>
      <div class="source-folder-area">
        <template v-if="directory">
          <div class="attached-folder">
            <AppIcon name="folder" :size="28" />
            <div>
              <strong>{{ directory.workspace_root.split(/[\\/]/).filter(Boolean).at(-1) }}</strong>
              <span>{{ directory.workspace_root }}</span>
            </div>
            <button
              type="button"
              class="icon-button"
              aria-label="移除源文件夹"
              :disabled="busy"
              @click="directory = null"
            >
              <AppIcon name="close" :size="17" />
            </button>
          </div>
          <button
            type="button"
            class="text-button"
            :disabled="busy || !connected"
            @click="chooseFolder"
          >
            {{ choosing ? '正在选择…' : '更换文件夹' }}
          </button>
        </template>
        <template v-else>
          <button
            type="button"
            class="source-folder-label"
            :disabled="busy || !connected"
            @click="chooseFolder"
          >
            <span>在此电脑上添加文件夹</span>
            <AppIcon name="down" :size="15" />
          </button>
          <button
            type="button"
            class="source-folder-add"
            :disabled="busy || !connected"
            @click="chooseFolder"
          >
            <AppIcon name="folder-plus" :size="20" />
            {{ choosing ? '正在选择…' : '添加' }}
          </button>
        </template>
        <div v-if="manual" class="manual-folder-form">
          <p>浏览器中请填写本机文件夹的完整路径。</p>
          <div>
            <input
              ref="pathInput"
              v-model="path"
              aria-label="源文件夹路径"
              placeholder="例如 E:\projects\my-app"
              maxlength="1000"
              :disabled="busy"
              @keydown.enter.prevent="attachFolder"
            />
            <button
              type="button"
              class="secondary-button"
              :disabled="busy || !path.trim()"
              @click="attachFolder"
            >
              {{ validating ? '检查中…' : '添加文件夹' }}
            </button>
          </div>
        </div>
      </div>
      <p v-if="project" class="project-edit-note">更换源文件夹后，新任务会使用新目录。</p>
      <p v-if="error" class="error-inline" role="alert">{{ error }}</p>
      <div class="dialog-actions">
        <button type="button" class="text-button" :disabled="busy" @click="emit('close')">
          取消
        </button>
        <button class="primary-button" :disabled="busy || !connected || !name.trim() || !directory">
          {{ saving ? '保存中…' : project ? '保存项目' : '创建项目' }}
        </button>
      </div>
    </form>
  </ModalDialog>
</template>
