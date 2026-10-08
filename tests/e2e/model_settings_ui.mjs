/** 真实本地 API 的模型设置验收；外部供应商由宿主的 SDK 离线传输替换。 */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const option = (name, fallback) =>
  process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : fallback
const url = option('--url', 'http://127.0.0.1:8767')
assert.ok(['localhost', '127.0.0.1'].includes(new URL(url).hostname))
const { chromium } = require(option('--playwright-module', 'playwright'))
const browser = await chromium.launch({
  executablePath: option('--browser', undefined),
  headless: true,
})
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.setDefaultTimeout(15000)
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const sidebar = page.getByRole('complementary', { name: '工作区导航' })
const api = (method, payload = {}) =>
  page.evaluate(
    async ({ method, payload }) => {
      const value = await (
        await fetch('/api/' + method, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Slothy-Client': 'desktop-ui' },
          body: JSON.stringify(payload),
        })
      ).json()
      if (!value.ok) throw new Error(value.error?.code)
      return value.data
    },
    { method, payload },
  )
const settings = () => sidebar.getByRole('button', { name: '设置', exact: true }).click()
const provider = (name) =>
  page
    .locator('.provider-options')
    .getByRole('button', { name: new RegExp(name) })
    .click()
const save = async () => {
  await page.getByRole('button', { name: '保存并使用', exact: true }).click()
  await page.getByText('已保存并设为当前模型，新任务立即生效。', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('模型 API Key', { exact: true }).inputValue(), '')
  assert.equal(
    await page.getByLabel('模型 API Key', { exact: true }).getAttribute('type'),
    'password',
  )
}
const setKey = (value) => page.getByLabel('模型 API Key', { exact: true }).fill(value)
const noOverflow = async () =>
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
const chooseModel = async (name) => {
  await page.getByRole('button', { name: /^切换模型，当前 / }).click()
  await page.getByRole('menuitemradio', { name, exact: true }).click()
  await page.getByRole('button', { name: '切换模型，当前 ' + name, exact: true }).waitFor()
}
const run = async (name, prompt) => {
  await page.getByLabel('任务输入', { exact: true }).fill(prompt)
  await page.getByRole('button', { name: '发送任务', exact: true }).click()
  await page
    .locator('.answer-text')
    .filter({ hasText: '已完成：' + name })
    .waitFor()
  const tasks = (await api('workspace')).tasks
  const task = tasks.find((item) => item.goal === prompt)
  assert.equal(task.model_binding.model, name)
  assert.equal(task.run.status, 'completed')
  return task
}
try {
  await mkdir('.slothy/desktop-qa', { recursive: true })
  await page.goto(url)
  await page.getByRole('button', { name: /^切换模型，当前 / }).waitFor()
  await settings()
  await page.locator('.provider-options button').first().waitFor()
  assert.equal(await page.locator('.provider-options button').count(), 4)
  await setKey('fake-ui-deepseek-key')
  await page.getByRole('button', { name: '显示', exact: true }).click()
  assert.equal(await page.getByLabel('模型 API Key', { exact: true }).getAttribute('type'), 'text')
  await save()
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await page.getByText('连接成功，所选模型可以响应。', { exact: true }).waitFor()
  await page.getByLabel('提供商模型').selectOption('deepseek-v4-pro')
  assert.equal(await page.getByRole('button', { name: '测试连接', exact: true }).isDisabled(), true)
  await save()
  await page
    .locator('.model-settings')
    .screenshot({ path: '.slothy/desktop-qa/model-providers-light.png' })

  await provider('Qwen')
  await setKey('fake-ui-qwen-key')
  await page.getByLabel('提供商模型').selectOption('qwen3-coder-plus')
  await save()
  await page.getByRole('combobox', { name: '服务区域' }).selectOption('international')
  assert.equal(
    await page.getByRole('button', { name: '保存并使用', exact: true }).isDisabled(),
    true,
  )
  await setKey('fake-ui-qwen-international-key')
  await save()
  assert.match((await api('workspace')).status.model.name, /qwen3-coder-plus/)

  await provider('MiMo')
  await setKey('fake-ui-mimo-key')
  await page.getByLabel('提供商模型').selectOption('__custom__')
  await page.getByLabel('自定义模型 ID').fill('mimo-custom-text')
  await save()
  assert.equal(await page.getByLabel('提供商模型').inputValue(), 'mimo-custom-text')

  await provider('GLM')
  await setKey('fake-invalid-glm-key')
  await save()
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: 'API Key 无效或没有访问权限' }).waitFor()
  assert.equal((await page.locator('body').innerText()).includes('fake-invalid-glm-key'), false)
  await setKey('fake-ui-glm-key')
  await save()
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await page.getByText('连接成功，所选模型可以响应。', { exact: true }).waitFor()
  await page
    .locator('.model-settings')
    .screenshot({ path: '.slothy/desktop-qa/model-providers-configured.png' })

  await provider('DeepSeek')
  await page.getByRole('button', { name: '刷新模型列表', exact: true }).click()
  await page.getByText('已更新提供商返回的文本模型列表。', { exact: true }).waitFor()
  assert.equal(
    await page.getByLabel('提供商模型').locator('option[value="account-text-model"]').count(),
    1,
  )
  assert.equal(
    await page.getByLabel('提供商模型').locator('option[value="text-embedding-v3"]').count(),
    0,
  )
  await page.keyboard.press('Control+k')
  await chooseModel('deepseek-flash')
  const old = await run('deepseek-flash', 'E2E DeepSeek 提供商任务')
  for (const [name, prompt] of [
    ['qwen-plus', 'E2E Qwen 提供商任务'],
    ['mimo-custom-text', 'E2E MiMo 提供商任务'],
    ['glm-5', 'E2E GLM 提供商任务'],
  ]) {
    await page.keyboard.press('Control+k')
    await chooseModel(name)
    await run(name, prompt)
  }
  assert.equal((await api('inspect_run', { run_id: old.run_id })).model, 'deepseek-flash')
  await page.keyboard.press('Control+k')
  await page.getByRole('button', { name: /^切换模型，当前 / }).click()
  await page
    .getByRole('menu', { name: '选择模型', exact: true })
    .screenshot({ path: '.slothy/desktop-qa/model-picker.png' })
  await page.keyboard.press('Escape')

  await sidebar.locator('.mode-trigger').click()
  await page.getByRole('menuitemradio', { name: /^sloty coding/ }).click()
  const ws = await api('workspace')
  const project = await api('create_project', {
    name: '模型 Coding 验证',
    workspace_root: ws.status.test_model_project,
  })
  await api('workspace')
  await sidebar.getByRole('button', { name: '设置', exact: true }).click()
  await sidebar.getByRole('button', { name: '新建任务', exact: true }).click()
  // 工作区轮询会同步刚刚创建的真实项目。
  await sidebar.locator('.project-toggle').filter({ hasText: project.name }).waitFor()
  await sidebar.locator('.project-toggle').filter({ hasText: project.name }).click()
  await run('glm-5', 'E2E Coding 模型绑定任务')
  assert.equal(
    (await api('workspace')).tasks.find((item) => item.goal === 'E2E Coding 模型绑定任务')
      .agent_mode,
    'coding',
  )

  await settings()
  await page.getByRole('button', { name: '深色', exact: true }).click()
  await provider('GLM')
  await page
    .locator('.model-settings')
    .screenshot({ path: '.slothy/desktop-qa/model-providers-dark.png' })
  await noOverflow()
  await page.setViewportSize({ width: 390, height: 844 })
  if (await sidebar.getByRole('button', { name: '折叠侧栏', exact: true }).isVisible())
    await sidebar.getByRole('button', { name: '折叠侧栏', exact: true }).click()
  await page.locator('.model-settings').scrollIntoViewIfNeeded()
  await noOverflow()
  await page.screenshot({ path: '.slothy/desktop-qa/model-providers-mobile.png' })
  assert.equal(await page.getByRole('button', { name: '保存并使用', exact: true }).isEnabled(), true)
  await page.getByRole('button', { name: '移除当前 API Key', exact: true }).click()
  await page.getByText('已移除当前服务区域的 API Key。', { exact: true }).waitFor()
  assert.equal((await api('model_settings')).providers.find((item) => item.id === 'glm').configured, false)
  const persisted = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  )
  assert.equal(persisted.includes('fake-ui-'), false)
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log(
    'PASS: 四家 API Key 配置、区域隔离、模型添加/刷新/切换、连接成功与鉴权失败、Chat/Coding 实际任务、旧任务绑定、密钥清空/浏览器存储、深浅主题与移动布局。',
  )
} finally {
  await browser.close()
}
