/** 真实测试宿主上的离线 UI 验收；不拦截或伪造前端 API。 */
import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const option = (name, fallback) =>
  process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : fallback
const url = option('--url', 'http://127.0.0.1:8766')
assert.ok(['localhost', '127.0.0.1'].includes(new URL(url).hostname))
const { chromium } = require(option('--playwright-module', 'playwright'))
const browser = await chromium.launch({
  executablePath: option('--browser', undefined),
  headless: true,
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
page.setDefaultTimeout(15000)
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const sidebar = page.getByRole('complementary', { name: '工作区导航' })
const screenshot = (name) =>
  page.screenshot({ path: '.slothy/desktop-qa/' + name + '.png', fullPage: true })
const noOverflow = async () =>
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
    false,
    '不应产生横向溢出',
  )
const api = (method, payload = {}) =>
  page.evaluate(
    async ({ method, payload }) => {
      const result = await (
        await fetch('/api/' + method, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Slothy-Client': 'desktop-ui' },
          body: JSON.stringify(payload),
        })
      ).json()
      if (!result.ok) throw new Error(result.error?.code)
      return result.data
    },
    { method, payload },
  )
async function mode(label) {
  await sidebar.locator('.mode-trigger').click()
  await page.getByRole('menuitemradio', { name: new RegExp('^' + label) }).click()
  await page.locator('.welcome-title h1').filter({ hasText: label }).waitFor()
}
async function budget(name) {
  await sidebar.getByRole('button', { name: '设置', exact: true }).click()
  await page
    .locator('.profile-options button')
    .filter({ has: page.getByText(name, { exact: true }) })
    .click()
  await page.keyboard.press('Control+k')
}
async function createProject(name, directory) {
  await sidebar.getByRole('button', { name: '创建项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '创建项目', exact: true })
  await dialog.getByLabel('项目名称').fill(name)
  assert.equal(
    await dialog.getByRole('button', { name: '创建项目', exact: true }).isDisabled(),
    true,
  )
  await dialog.getByRole('button', { name: '添加', exact: true }).click()
  await dialog.getByLabel('源文件夹路径').fill(directory)
  await dialog.getByRole('button', { name: '添加文件夹', exact: true }).click()
  await dialog.locator('.attached-folder').waitFor()
  await dialog.getByRole('button', { name: '创建项目', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
}
async function send(goal) {
  await page.keyboard.press('Control+k')
  await page.getByLabel('任务输入').fill(goal)
  await page.getByRole('button', { name: '发送任务', exact: true }).click()
}
async function approve() {
  await page.getByRole('button', { name: '批准本次尝试', exact: true }).click()
  await page.locator('.approval-result').waitFor()
  assert.equal(await page.locator('.run-badge.waiting_approval').count(), 1, '决定不隐式恢复')
  await page.getByRole('button', { name: '继续执行', exact: true }).click()
}
await mkdir('.slothy/desktop-qa', { recursive: true })
try {
  await page.goto(url)
  await page.locator('.connection-control .online').waitFor()
  assert.equal(await page.locator('h1').innerText(), 'slothy chat')
  assert.equal(await sidebar.locator('.coding-projects').count(), 0)
  assert.equal(
    await page.locator('.task-composer select, .profile-switch, .agent-mode-select').count(),
    0,
  )
  const host = await api('workspace')
  assert.match(host.status.test_coding_root, /slothy-ui-test-/)
  const codingRoot = host.status.test_coding_root
  const secondRoot = host.status.test_second_root
  assert.ok(secondRoot)
  await noOverflow()
  await screenshot('chat-mode')
  await sidebar.locator('.mode-trigger').focus()
  await page.keyboard.press('Enter')
  assert.match(await page.evaluate(() => document.activeElement?.textContent), /slothy chat/)
  await page.keyboard.press('ArrowDown')
  assert.match(await page.evaluate(() => document.activeElement?.textContent), /sloty coding/)
  await screenshot('mode-menu')
  await page.keyboard.press('Escape')

  await page.getByLabel('任务输入').fill('Chat 草稿保持独立')
  await mode('sloty coding')
  assert.equal(await page.getByLabel('任务输入').inputValue(), '')
  await sidebar.getByRole('region', { name: '项目环境' }).waitFor()
  assert.equal(await page.getByRole('button', { name: '发送任务', exact: true }).isDisabled(), true)
  assert.equal(await page.locator('.workspace-picker, .coding-workspace-hint').count(), 0)
  await page.getByLabel('任务输入').fill('Coding 草稿保持独立')
  await mode('slothy chat')
  assert.equal(await page.getByLabel('任务输入').inputValue(), 'Chat 草稿保持独立')
  await mode('sloty coding')
  assert.equal(await page.getByLabel('任务输入').inputValue(), 'Coding 草稿保持独立')

  // 按参考图创建项目，目录必须通过宿主验证，取消不会写入。
  await sidebar.getByRole('button', { name: '创建项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '创建项目', exact: true })
  await dialog.getByLabel('项目名称').fill('取消的项目')
  await page.keyboard.press('Shift+Tab')
  assert.equal(await page.evaluate(() => document.activeElement?.closest('dialog') !== null), true)
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.equal((await api('workspace')).projects.length, 0)
  await sidebar.getByRole('button', { name: '创建项目', exact: true }).click()
  await dialog.getByLabel('项目名称').fill('slothy harness')
  await screenshot('create-project')
  await dialog.getByRole('button', { name: '添加', exact: true }).click()
  await dialog.getByLabel('源文件夹路径').fill('missing-relative-root')
  await dialog.getByRole('button', { name: '添加文件夹', exact: true }).click()
  await dialog.locator('.error-inline').waitFor()
  assert.equal(
    await dialog.getByRole('button', { name: '创建项目', exact: true }).isDisabled(),
    true,
  )
  await dialog.getByLabel('源文件夹路径').fill(codingRoot)
  await dialog.getByRole('button', { name: '添加文件夹', exact: true }).click()
  await dialog.locator('.attached-folder').waitFor()
  await screenshot('create-project-attached')
  await dialog.getByRole('button', { name: '创建项目', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  const project = (await api('workspace')).projects.find((item) => item.name === 'slothy harness')
  assert.equal(project.repository.label, 'Mzys521/slothy-harness')
  const group = sidebar.locator('[data-project-id="' + project.id + '"]')
  await group.waitFor()
  await group.getByRole('button', { name: 'slothy harness 项目详情', exact: true }).click()
  const details = page.getByRole('dialog', { name: 'slothy harness 项目详情菜单', exact: true })
  assert.match(await details.innerText(), /0 个任务/)
  assert.match(await details.innerText(), /Mzys521\/slothy-harness/)
  assert.ok((await details.innerText()).includes(codingRoot))
  await screenshot('project-details')
  await page.keyboard.press('Escape')

  await createProject('第二项目', secondRoot)
  await sidebar.getByRole('button', { name: '在 slothy harness 中新建任务', exact: true }).click()
  await sidebar.getByRole('button', { name: '设置', exact: true }).click()
  assert.equal(await page.getByLabel('Coding Agent 工作目录').count(), 0)
  await page.getByLabel('检查超时秒数').fill('20')
  await page.getByRole('button', { name: '保存 Coding 权限', exact: true }).click()
  await page.getByText('sloty coding 设置已保存，将应用于新任务。', { exact: true }).waitFor()
  await screenshot('coding-permissions')
  await sidebar.getByRole('button', { name: '工具链', exact: true }).click()
  await page.getByRole('heading', { name: 'edit_file', exact: true }).waitFor()
  assert.equal(await page.locator('.tool-definition').count(), 9)
  await budget('进阶')
  const codingGoal = 'E2E Coding：读取项目、修改 VALUE 并运行单元测试'
  await send(codingGoal)
  await page.locator('.approval-card').filter({ hasText: 'edit_file' }).waitFor()
  assert.equal(await readFile(join(codingRoot, 'sample.py'), 'utf8'), 'VALUE = 1\n')
  assert.equal((await api('workspace')).tasks[0].coding_binding.workspace_root, codingRoot)
  await page.getByText('查看本次请求参数', { exact: true }).click()
  assert.match(await page.locator('.approval-card pre').innerText(), /expected_sha256/)
  await screenshot('coding-approval')
  await approve()
  await page.locator('.approval-card').filter({ hasText: 'run_checks' }).waitFor()
  assert.equal(await readFile(join(codingRoot, 'sample.py'), 'utf8'), 'VALUE = 2\n')
  assert.equal(await readFile(join(secondRoot, 'sample.py'), 'utf8'), 'VALUE = 1\n')
  await approve()
  await page.locator('.run-badge.completed').waitFor()
  await page.locator('.answer-text').filter({ hasText: 'Coding 工具流程已完成' }).waitFor()
  assert.match(await page.locator('.timeline').innerText(), /read_file/)
  assert.match(await page.locator('.timeline').innerText(), /edit_file/)
  assert.match(await page.locator('.timeline').innerText(), /run_checks/)
  assert.equal(await page.locator('.process-node.waiting').count(), 0)
  await group.locator('.sidebar-task').filter({ hasText: codingGoal }).waitFor()
  await screenshot('coding-project-tasks')
  await group.getByRole('button', { name: '折叠项目 slothy harness', exact: true }).click()
  assert.equal(await group.locator('.sidebar-task').count(), 0)
  await group.getByRole('button', { name: '展开项目 slothy harness', exact: true }).click()
  assert.equal(await group.locator('.sidebar-task').count(), 1)
  await group.getByRole('button', { name: 'slothy harness 项目详情', exact: true }).click()
  assert.match(await details.innerText(), /1 个任务/)
  await details.getByRole('button', { name: '置顶项目 slothy harness', exact: true }).click()
  await group
    .locator('.project-details [aria-label="取消置顶项目 slothy harness"]')
    .waitFor({ state: 'attached' })
  await group.getByRole('button', { name: 'slothy harness 项目详情', exact: true }).click()
  await details.getByRole('button', { name: '取消置顶项目 slothy harness', exact: true }).waitFor()
  await screenshot('project-details-with-task')
  await details.getByRole('button', { name: '编辑项目', exact: true }).click()
  const edit = page.getByRole('dialog', { name: '编辑项目', exact: true })
  await edit.getByLabel('项目名称').fill('slothy harness 重命名')
  await edit.getByRole('button', { name: '更换文件夹', exact: true }).click()
  await edit.getByLabel('源文件夹路径').fill(secondRoot)
  await edit.getByRole('button', { name: '添加文件夹', exact: true }).click()
  await edit.locator('.manual-folder-form').waitFor({ state: 'hidden' })
  await edit.getByRole('button', { name: '保存项目', exact: true }).click()
  await edit.waitFor({ state: 'hidden' })
  const changed = (await api('workspace')).projects.find((item) => item.id === project.id)
  assert.equal(changed.workspace_root, secondRoot)
  assert.equal(changed.pinned, true)
  assert.equal(
    (await api('workspace')).tasks[0].coding_binding.workspace_root,
    codingRoot,
    '换目录不改写旧任务',
  )
  await group.getByRole('button', { name: '折叠项目 slothy harness 重命名', exact: true }).click()
  await page.reload()
  await page.locator('.connection-control .online').waitFor()
  assert.equal(await page.locator('h1').innerText(), 'sloty coding')
  assert.equal(await group.locator('.sidebar-task').count(), 0, '刷新后保留折叠状态')
  assert.equal(
    (await api('workspace')).projects.find((item) => item.id === project.id).pinned,
    true,
  )

  // 两种模式的任务、草稿、工具和环境分开，切换不中断已经启动的任务。
  await mode('slothy chat')
  assert.equal(await sidebar.locator('.coding-projects, .project-group').count(), 0)
  assert.equal(await sidebar.locator('.sidebar-task').count(), 0, 'Chat 不显示 Coding 任务')
  await sidebar.getByRole('button', { name: '设置', exact: true }).click()
  assert.equal(await page.locator('.coding-settings').count(), 0)
  await sidebar.getByRole('button', { name: '工具链', exact: true }).click()
  await page.getByRole('heading', { name: 'add', exact: true }).waitFor()
  assert.equal(await page.locator('.tool-definition').count(), 3)
  await budget('进阶')
  await send('检索 A-123，调用 add，并验证重试与最终结果。')
  await page.locator('.run-badge.completed').waitFor()
  await page.locator('.answer-text').filter({ hasText: '42.3' }).waitFor()
  assert.match(await page.locator('.run-controls').innerText(), /3 \/ 20 轮/)
  assert.match(await page.locator('.timeline').innerText(), /重试 1 次/)
  assert.match(await page.locator('.runtime-status').innerText(), /9 tokens/)
  await screenshot('chat-completed')
  await page.keyboard.press('Control+p')
  await page.getByLabel('搜索任务名称').fill('E2E Coding')
  assert.equal(await page.locator('.search-results button').count(), 0, '搜索遵循当前模式')
  await page.keyboard.press('Escape')
  await page.keyboard.press('Control+k')
  await page.getByLabel('任务输入').fill('/add')
  await page.locator('.composer-menu').waitFor()
  assert.equal(await page.locator('.composer-menu > button').count(), 1)
  await page.keyboard.press('Escape')
  await page.getByLabel('任务输入').fill('输入法组字测试')
  await page.getByLabel('任务输入').evaluate((input) =>
    input.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'Enter',
        isComposing: true,
        bubbles: true,
        cancelable: true,
      }),
    ),
  )
  assert.equal(await page.locator('.run-view').count(), 0)

  const createdResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/create_task'),
  )
  const executedResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/execute_run'),
  )
  await send('E2E 控制：创建期间切换不会覆盖新的模式与草稿')
  await mode('sloty coding')
  await page.getByLabel('任务输入').fill('切换后的 Coding 草稿')
  await createdResponse
  await executedResponse
  assert.equal(await page.locator('h1').innerText(), 'sloty coding', '迟到的创建响应不能切回 Chat')
  assert.equal(await page.getByLabel('任务输入').inputValue(), '切换后的 Coding 草稿')
  await mode('slothy chat')
  await sidebar
    .locator('.sidebar-task')
    .filter({ hasText: 'E2E 控制：创建期间切换不会覆盖新的模式与草稿' })
    .click()
  await page.locator('.run-badge.completed').waitFor()

  await send('E2E 控制：切换模式不会取消正在执行的任务')
  await page.locator('.run-badge.thinking').waitFor()
  await mode('sloty coding')
  await mode('slothy chat')
  const background = sidebar
    .locator('.sidebar-task')
    .filter({ hasText: 'E2E 控制：切换模式不会取消正在执行的任务' })
  await background.click()
  await page.locator('.run-badge.completed').waitFor()
  assert.equal(await page.locator('.answer-text').innerText(), '控制用例完成')
  await send('E2E 控制：暂停任务并显式继续')
  await page.locator('.run-badge.thinking').waitFor()
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await page.locator('.run-badge.suspended').waitFor()
  await page.getByRole('button', { name: '继续执行', exact: true }).click()
  await page.locator('.run-badge.completed').waitFor()
  await send('E2E 控制：取消正在处理的任务')
  await page.locator('.run-badge.thinking').waitFor()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.locator('.run-badge.cancelled').waitFor()
  assert.equal(await page.locator('.answer-text, .notice-bar.error').count(), 0)

  // 保留完成后才入库的记忆修复。
  const previousQuestion = 'E2E 记忆：请记住这是上一轮真实完成的任务'
  await send(previousQuestion)
  await page.locator('.answer-text').filter({ hasText: '前一轮任务已完成' }).waitFor()
  await send('我刚刚问了什么？')
  await page.locator('.answer-text').filter({ hasText: previousQuestion }).waitFor()
  assert.equal(
    await page.locator('.answer-text').innerText(),
    '你上一轮问的是：' + previousQuestion,
  )

  await mode('sloty coding')
  await page.getByRole('button', { name: '切换到深色主题', exact: true }).click()
  const brand = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement)
    return ['--slothy-green', '--slothy-cream', '--slothy-brown'].map((name) =>
      style.getPropertyValue(name).trim().toUpperCase(),
    )
  })
  assert.deepEqual(brand, ['#60DD06', '#FCEAC9', '#95611F'])
  await group.getByRole('button', { name: '展开项目 slothy harness 重命名', exact: true }).click()
  await screenshot('coding-projects-dark')
  await group.getByRole('button', { name: 'slothy harness 重命名 项目详情', exact: true }).click()
  await screenshot('project-details-dark')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '切换到浅色主题', exact: true }).click()
  await sidebar.getByRole('button', { name: '折叠侧栏', exact: true }).click()
  assert.equal(await sidebar.evaluate((el) => Math.round(el.getBoundingClientRect().width)), 76)
  await mode('slothy chat')
  await page.setViewportSize({ width: 880, height: 700 })
  await noOverflow()
  await screenshot('compact-new-sidebar')
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await sidebar.evaluate((el) => Math.round(el.getBoundingClientRect().width)), 60)
  await mode('sloty coding')
  await sidebar.getByRole('button', { name: '展开侧栏', exact: true }).click()
  await sidebar.locator('.coding-projects').waitFor()
  await sidebar.getByRole('button', { name: '创建项目', exact: true }).click()
  await noOverflow()
  await screenshot('create-project-narrow')
  await page.keyboard.press('Escape')
  await sidebar.getByRole('button', { name: '折叠侧栏', exact: true }).click()
  for (const name of ['工具链', '长期记忆', '灵感库', '运行日志', '设置']) {
    await sidebar.getByRole('button', { name, exact: true }).click()
    await noOverflow()
  }
  await page.keyboard.press('Control+k')
  await noOverflow()
  await screenshot('narrow-coding')
  assert.deepEqual(errors, [])
  console.log(
    'PASS: top sidebar modes, project folder validation/create/edit/pin/persistence, collapse/tasks/details, mode isolation/drafts/background execution, real Coding edit/check approvals, chat/retries/memory/controls, themes and responsive UI',
  )
} catch (error) {
  await screenshot('e2e-failure')
  console.error('Failure workspace:', (await api('workspace')).projects)
  throw error
} finally {
  await browser.close()
}
