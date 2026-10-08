<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import { useWorkspace } from '../stores/workspace'
const emit = defineEmits<{ prompt: [string]; plugins: [] }>()
const { tools, connected, modeLabel, toolsLoading } = useWorkspace()
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <span class="page-eyebrow">CAPABILITIES</span>
        <h1>工具链</h1>
        <p>让每一次调用都有清晰的边界。</p>
      </div>
      <button class="secondary-button" @click="emit('plugins')">
        <AppIcon name="tool" :size="15" />
        插件
      </button>
    </header>
    <div class="section-caption">
      <span>{{ modeLabel }} 工具</span>
      <span>{{ tools.length }} 个工具</span>
    </div>
    <div class="tool-list">
      <article v-for="tool in tools" :key="tool.name" class="tool-definition">
        <div class="tool-description">
          <span class="tool-glyph">
            <AppIcon
              :name="
                tool.name === 'search_memory'
                  ? 'memory'
                  : tool.name === 'get_result'
                    ? 'logs'
                    : 'tool'
              "
              :size="20"
            />
          </span>
          <div>
            <h2>{{ tool.name }}</h2>
            <p>{{ tool.description }}</p>
          </div>
          <span class="neutral-badge">{{ tool.replay_safety }}</span>
        </div>
        <details class="tool-schema">
          <summary>
            参数定义
            <AppIcon name="down" :size="12" />
          </summary>
          <pre>{{ JSON.stringify(tool.parameters, null, 2) }}</pre>
        </details>
        <div class="tool-footer">
          <span>
            {{
              tool.timeout_seconds === null
                ? '未配置工具时限'
                : `时限配置 ${tool.timeout_seconds} 秒`
            }}
          </span>
          <button
            class="text-button"
            @click="emit('prompt', `请使用 ${tool.name} 工具完成以下任务：`)"
          >
            在任务中使用
            <AppIcon name="chevron" :size="14" />
          </button>
        </div>
      </article>
    </div>
    <div v-if="!tools.length" class="page-empty">
      <AppIcon name="tool" :size="34" />
      <h2>
        {{ toolsLoading ? '正在加载工具…' : connected ? '还没有注册工具' : '连接后查看工具' }}
      </h2>
      <p>可用工具会从本地服务的真实目录加载。</p>
    </div>
    <p class="page-footnote">
      <AppIcon name="shield" :size="14" />
      工具调用经过参数校验、策略与权限检查，并记录运行事件。
    </p>
  </section>
</template>
