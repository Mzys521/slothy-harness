<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkspace } from '../stores/workspace'
import { request } from '../services/bridge'
import type { ModelProviderSettings } from '../types/desktop'

const {
  workspace,
  connected,
  modelBusy,
  saveModelProvider,
  removeModelKey,
  refreshProviderModels,
} = useWorkspace()
const providers = computed(() => workspace.value?.status.model_settings?.providers || [])
const providerId = ref('deepseek')
const provider = computed(() => providers.value.find((item) => item.id === providerId.value))
const endpointId = ref(''),
  model = ref(''),
  customModel = ref(''),
  apiKey = ref('')
const visible = ref(false),
  dirty = ref(false),
  pending = ref(''),
  error = ref(''),
  message = ref('')
let initialized = false
const currentEndpoint = computed(() =>
  provider.value?.endpoints.find((item) => item.id === endpointId.value),
)
const hasKey = computed(() => currentEndpoint.value?.configured === true)
const modelId = computed(() =>
  model.value === '__custom__' ? customModel.value.trim() : model.value,
)
const locked = computed(() => !connected.value || !!pending.value || modelBusy.value)
const isActive = computed(
  () => workspace.value?.status.model_settings?.selection?.provider_id === providerId.value,
)
const canTest = computed(() => hasKey.value && !dirty.value && !apiKey.value && !!modelId.value)
const source = computed(() => workspace.value?.status.model_settings?.storage_kind)

function load(item: ModelProviderSettings) {
  endpointId.value = item.endpoint_id
  model.value = item.model
  customModel.value = ''
  apiKey.value = ''
  visible.value = false
  dirty.value = false
}
watch(
  providers,
  (items) => {
    if (!initialized && items.length) {
      providerId.value =
        workspace.value?.status.model_settings?.selection?.provider_id || items[0]!.id
      initialized = true
    }
    const item = items.find((value) => value.id === providerId.value)
    if (item && !dirty.value && !pending.value) load(item)
  },
  { immediate: true },
)
function choose(id: string) {
  if (locked.value) return
  providerId.value = id
  const item = provider.value
  if (item) load(item)
  error.value = message.value = ''
}
function changeEndpoint() {
  apiKey.value = ''
  visible.value = false
  dirty.value = true
  error.value = message.value = ''
}
function binding() {
  return { provider_id: providerId.value, endpoint_id: endpointId.value, model: modelId.value }
}
async function action(kind: 'save' | 'test' | 'refresh' | 'remove') {
  if (locked.value) return
  pending.value = kind
  error.value = message.value = ''
  try {
    if (kind === 'save') {
      await saveModelProvider({
        ...binding(),
        ...(apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}),
      })
      dirty.value = false
      if (provider.value) load(provider.value)
      message.value = '已保存并设为当前模型，新任务立即生效。'
    } else if (kind === 'test') {
      await request('test_model_connection', binding())
      message.value = '连接成功，所选模型可以响应。'
    } else if (kind === 'refresh') {
      await refreshProviderModels(binding())
      message.value = '已更新提供商返回的文本模型列表。'
    } else {
      await removeModelKey(providerId.value, endpointId.value)
      dirty.value = false
      if (provider.value) load(provider.value)
      message.value = '已移除当前服务区域的 API Key。'
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '操作失败，请重试。'
  } finally {
    apiKey.value = ''
    visible.value = false
    pending.value = ''
  }
}
</script>

<template>
  <section class="settings-section model-settings" aria-labelledby="model-settings-heading">
    <div class="settings-section-heading">
      <h2 id="model-settings-heading">模型提供商</h2>
      <span class="subtle-text">{{ workspace?.status.model.name || '选择你的模型' }}</span>
    </div>
    <p class="subtle-text">选择提供商，填入 API Key 即可开始。模型切换应用于新任务。</p>
    <div class="provider-options" role="group" aria-label="模型提供商">
      <button
        v-for="item in providers"
        :key="item.id"
        :disabled="locked"
        :aria-pressed="providerId === item.id"
        :class="{ chosen: providerId === item.id }"
        @click="choose(item.id)"
      >
        <span class="provider-monogram">
          {{
            item.id === 'deepseek' ? 'D' : item.id === 'qwen' ? 'Q' : item.id === 'mimo' ? 'M' : 'G'
          }}
        </span>
        <span>
          <strong>{{ item.name.split(' · ')[0] }}</strong>
          <small>{{ item.configured ? '已配置' : '添加 API Key' }}</small>
        </span>
        <AppIcon v-if="providerId === item.id" name="check" :size="14" />
      </button>
    </div>
    <form v-if="provider" class="provider-form" @submit.prevent="action('save')">
      <div class="provider-form-heading">
        <strong>{{ provider.name }}</strong>
        <span v-if="isActive" class="model-active-label">当前提供商</span>
        <a :href="provider.key_url" target="_blank" rel="noopener noreferrer">
          获取 API Key
          <AppIcon name="link" :size="12" />
        </a>
      </div>
      <label v-if="provider.endpoints.length > 1" class="model-field">
        <span>服务区域</span>
        <select v-model="endpointId" :disabled="locked" @change="changeEndpoint">
          <option v-for="item in provider.endpoints" :key="item.id" :value="item.id">
            {{ item.label }}
          </option>
        </select>
        <small>请选择 API Key 所属区域，各区域的密钥独立保存。</small>
      </label>
      <label class="model-field">
        <span>
          API Key
          <small>{{ hasKey ? '已保存，留空保留现有密钥' : '仅用于连接所选提供商' }}</small>
        </span>
        <span class="model-key-input">
          <input
            v-model="apiKey"
            aria-label="模型 API Key"
            :type="visible ? 'text' : 'password'"
            autocomplete="off"
            spellcheck="false"
            maxlength="4096"
            :disabled="locked"
            :placeholder="hasKey ? '•••••••• 已安全保存' : '输入你的 API Key'"
            @input="dirty = true"
          />
          <button
            type="button"
            class="text-button"
            :disabled="locked || !apiKey"
            @click="visible = !visible"
          >
            {{ visible ? '隐藏' : '显示' }}
          </button>
        </span>
      </label>
      <label class="model-field">
        <span>模型</span>
        <select v-model="model" aria-label="提供商模型" :disabled="locked" @change="dirty = true">
          <option v-for="item in provider.models" :key="item" :value="item">{{ item }}</option>
          <option value="__custom__">添加其他模型 ID…</option>
        </select>
      </label>
      <label v-if="model === '__custom__'" class="model-field">
        <span>模型 ID</span>
        <input
          v-model="customModel"
          aria-label="自定义模型 ID"
          placeholder="填写提供商支持的文本模型 ID"
          maxlength="128"
          required
          :disabled="locked"
          @input="dirty = true"
        />
        <small>添加后可直接切换，模型需支持文本生成与 Function Calling。</small>
      </label>
      <div class="provider-endpoint">
        <span>{{ currentEndpoint?.base_url }}</span>
        <a :href="provider.documentation_url" target="_blank" rel="noopener noreferrer">接口文档</a>
      </div>
      <p v-if="source === 'windows_dpapi'" class="model-storage-note">
        <AppIcon name="shield" :size="14" />
        API Key 由 Windows 加密保存在本机，保存后不会回传到页面。
      </p>
      <p v-else-if="source === 'session'" class="model-storage-note">
        <AppIcon name="shield" :size="14" />
        当前平台仅在本次进程内保留 API Key，重启后需要重新填写。
      </p>
      <p v-if="error" class="error-inline" role="alert">{{ error }}</p>
      <p v-if="message" class="model-feedback" role="status">{{ message }}</p>
      <div class="model-actions">
        <button
          type="button"
          class="secondary-button small"
          :disabled="locked || !canTest"
          @click="action('test')"
        >
          {{ pending === 'test' ? '正在测试…' : '测试连接' }}
        </button>
        <button
          v-if="provider.can_list_models"
          type="button"
          class="text-button"
          :disabled="locked || !canTest"
          @click="action('refresh')"
        >
          <AppIcon name="refresh" :size="13" />
          {{ pending === 'refresh' ? '正在更新…' : '刷新模型列表' }}
        </button>
        <button
          type="submit"
          class="primary-button"
          :disabled="locked || !modelId || (!hasKey && !apiKey.trim())"
        >
          {{ pending === 'save' ? '正在保存…' : '保存并使用' }}
        </button>
      </div>
      <div v-if="hasKey" class="model-remove">
        <button type="button" class="text-button" :disabled="locked" @click="action('remove')">
          移除当前 API Key
        </button>
        <small>移除后，该提供商的任务需要重新配置密钥。</small>
      </div>
    </form>
    <p v-else class="subtle-text">连接本地服务后即可配置模型。</p>
  </section>
</template>
