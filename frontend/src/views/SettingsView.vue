<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ModelSettings from '../components/ModelSettings.vue'
import { useAppearance } from '../stores/appearance'
import type { Appearance } from '../stores/appearance'
import { formatTokens } from '../services/eventProjection'
import { useWorkspace } from '../stores/workspace'
import type { CodingSettings, CodingSettingsUpdate } from '../types/desktop'
const {
  workspace,
  connected,
  configured,
  connecting,
  profile,
  agentMode,
  modeLabel,
  modeProfiles,
  connect,
  saveCodingSettings,
} = useWorkspace()
const form = reactive<CodingSettingsUpdate>({
  allow_edits: true,
  allowed_checks: [],
  check_timeout_seconds: 60,
})
const dirty = ref(false),
  saving = ref(false),
  error = ref('')
function loadForm(value: CodingSettings) {
  Object.assign(form, {
    allow_edits: value.allow_edits,
    check_timeout_seconds: value.check_timeout_seconds,
    allowed_checks: [...value.allowed_checks],
  })
}
watch(
  () => workspace.value?.status.coding_settings,
  (value) => {
    if (value && !dirty.value) loadForm(value)
  },
  { immediate: true },
)
async function saveCoding() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    const value = await saveCodingSettings({
      ...form,
      allowed_checks: [...form.allowed_checks],
    })
    dirty.value = false
    loadForm(value)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '设置保存失败。'
  } finally {
    saving.value = false
  }
}
const { preference, setAppearance } = useAppearance()
const themes: { id: Appearance; label: string; icon: string }[] = [
  { id: 'light', label: '浅色', icon: 'sun' },
  { id: 'dark', label: '深色', icon: 'moon' },
  { id: 'system', label: '跟随系统', icon: 'monitor' },
]
const profiles = computed(() =>
  modeProfiles.value
    ? (['quick', 'advanced'] as const).map((id) => ({
        id,
        ...modeProfiles.value![id],
      }))
    : [],
)
</script>

<template>
  <section class="page-view settings-view">
    <header class="page-heading">
      <div>
        <span class="page-eyebrow">PREFERENCES</span>
        <h1>设置</h1>
        <p>一个适合你的工作区。</p>
      </div>
    </header>
    <section class="settings-section">
      <h2>外观</h2>
      <p class="subtle-text">选择界面主题。</p>
      <div class="appearance-options">
        <button
          v-for="theme in themes"
          :key="theme.id"
          :class="{ chosen: preference === theme.id }"
          :aria-pressed="preference === theme.id"
          @click="setAppearance(theme.id)"
        >
          <AppIcon :name="theme.icon" :size="20" />
          <span>{{ theme.label }}</span>
          <AppIcon v-if="preference === theme.id" name="check" :size="15" />
        </button>
      </div>
    </section>
    <section class="settings-section">
      <div class="settings-section-heading">
        <h2>本地服务</h2>
        <button class="text-button" :disabled="connecting" @click="connect">
          <AppIcon name="refresh" :size="14" />
          {{ connecting ? '连接中…' : '刷新连接' }}
        </button>
      </div>
      <dl class="settings-data">
        <div>
          <dt>服务连接</dt>
          <dd>
            <i class="connection-dot" :class="{ online: connected }"></i>
            {{ connected ? '已连接' : '尚未连接' }}
          </dd>
        </div>
        <div>
          <dt>文本模型</dt>
          <dd>{{ workspace?.status.model.name || '尚未配置' }}</dd>
        </div>
        <div>
          <dt>模型提供方</dt>
          <dd>{{ workspace?.status.model.provider || '—' }}</dd>
        </div>
        <div>
          <dt>版本</dt>
          <dd>{{ workspace?.status.version || '—' }}</dd>
        </div>
      </dl>
      <div v-if="connected && !configured" class="setup-card">
        <AppIcon name="settings" :size="18" />
        <div>
          <strong>配置文本模型后即可开始任务</strong>
          <p>在下方选择模型提供商并保存 API Key，即可开始任务。</p>
        </div>
      </div>
    </section>
    <ModelSettings />
    <section v-if="agentMode === 'coding'" class="settings-section coding-settings">
      <h2>sloty coding 权限</h2>
      <p class="subtle-text">源文件夹在项目中配置。文件修改与运行检查均需要你批准本次调用。</p>
      <form class="coding-settings-form" @submit.prevent="saveCoding">
        <label class="coding-checkbox">
          <input
            v-model="form.allow_edits"
            type="checkbox"
            :disabled="!connected || saving"
            @change="dirty = true"
          />
          <span>
            允许申请修改文件
            <small>关闭后仅提供文件阅读与检索工具</small>
          </span>
        </label>
        <fieldset :disabled="!connected || saving">
          <legend>允许申请运行的项目检查</legend>
          <p class="subtle-text">测试和构建会执行项目代码，请在审批卡片中确认检查预设。</p>
          <label
            v-for="preset in workspace?.status.check_presets || []"
            :key="preset.id"
            class="coding-checkbox"
          >
            <input
              v-model="form.allowed_checks"
              type="checkbox"
              :value="preset.id"
              @change="dirty = true"
            />
            <span>{{ preset.label }}</span>
          </label>
        </fieldset>
        <label class="coding-field coding-timeout">
          <span>单次检查最长时间（秒）</span>
          <input
            v-model.number="form.check_timeout_seconds"
            aria-label="检查超时秒数"
            type="number"
            min="1"
            max="120"
            required
            :disabled="!connected || saving"
            @input="dirty = true"
          />
        </label>
        <p v-if="error" class="error-inline" role="alert">{{ error }}</p>
        <div class="coding-settings-actions">
          <span class="subtle-text">保存在本机，应用于新任务。</span>
          <button class="primary-button" :disabled="!connected || saving || !dirty">
            {{ saving ? '正在保存…' : '保存 Coding 权限' }}
          </button>
        </div>
      </form>
    </section>
    <section class="settings-section">
      <h2>执行预算</h2>
      <p class="subtle-text">
        {{ modeLabel }}
        的执行预算，应用于下一次新建任务。
      </p>
      <div class="profile-options">
        <button
          v-for="item in profiles"
          :key="item.id"
          :class="{ chosen: profile === item.id }"
          :aria-pressed="profile === item.id"
          @click="profile = item.id"
        >
          <AppIcon :name="item.id === 'quick' ? 'sparkles' : 'code'" :size="20" />
          <span>
            <strong>{{ item.label }}</strong>
            <small>最多 {{ item.max_steps }} 轮 · {{ item.timeout_seconds }} 秒</small>
          </span>
          <AppIcon v-if="profile === item.id" name="check" :size="16" />
        </button>
      </div>
    </section>
    <section v-if="workspace" class="settings-section">
      <h2>上下文预算</h2>
      <dl class="settings-data">
        <div>
          <dt>模型窗口</dt>
          <dd>{{ formatTokens(workspace.status.context_config.model_window) }} tokens</dd>
        </div>
        <div>
          <dt>输出预留</dt>
          <dd>{{ formatTokens(workspace.status.context_config.output_reserve) }} tokens</dd>
        </div>
        <div>
          <dt>安全余量</dt>
          <dd>{{ formatTokens(workspace.status.context_config.safety_margin) }} tokens</dd>
        </div>
      </dl>
      <p class="subtle-text">输入用量由计数器估算，实际用量以模型服务返回为准。</p>
    </section>
    <section class="settings-section about-section">
      <img src="/brand/slothy-symbol.png" alt="" />
      <div>
        <strong>Slothy · 思洛</strong>
        <p>小步前行，认真完成。</p>
        <span>界面参考 DeepSeek Harness · Vue 3</span>
      </div>
    </section>
  </section>
</template>
