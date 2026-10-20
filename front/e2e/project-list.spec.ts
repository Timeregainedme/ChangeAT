import { expect, test, type Page } from '@playwright/test'

/**
 * 项目列表页的主链路用例。
 *
 * 用 MSW mock 数据 + 伪造登录态，不依赖后端与真实账号：
 * 这样这条用例可以在任何机器和 CI 上稳定跑，验证的是「页面能读、能筛、能开弹窗」，
 * 而不是后端实现。真实接口的契约由 generated client 的类型保证。
 */
async function signIn(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('dyeingtime_token', 'e2e-token')
    localStorage.setItem(
      'dyeingtime_user',
      JSON.stringify({ id: '1', username: 'e2e', display_name: 'E2E' }),
    )
    localStorage.setItem('dyeingtime_language', 'zh-CN')
  })
}

test('项目列表渲染卡片，并显示下一步动作', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects')

  await expect(page.getByRole('heading', { name: '项目', level: 1 })).toBeVisible()
  await expect(page.getByText('古风权谋·长安夜')).toBeVisible()
  // 卡片必须回答「现在该做什么」，这是列表页存在的核心价值
  await expect(page.getByText('下一步').first()).toBeVisible()
})

test('搜索可以过滤卡片，清空后恢复', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects')

  const search = page.getByPlaceholder('搜索项目名称或简介')
  await search.fill('长安')
  await expect(page.getByText('古风权谋·长安夜')).toBeVisible()
  await expect(page.getByText('赛博朋克追击')).toHaveCount(0)

  await search.fill('')
  await expect(page.getByText('赛博朋克追击')).toBeVisible()
})

test('新建项目弹窗可打开并关闭', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects')

  await page.getByRole('button', { name: '新建项目' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('新建项目')).toBeVisible()
  await expect(dialog.getByLabel('项目名称')).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})
