import { expect, test, type Page } from '@playwright/test'

/**
 * 风格管理用例。
 *
 * 覆盖最有价值的一条链路：新增风格后，**不刷新页面**回到项目列表，
 * 新建项目弹窗就能看到新风格。这同时验证了「风格目录缓存失效」是否生效——
 * 之前这里有一层模块级缓存，不改的话新增风格要手动刷新才出现。
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

test('新增风格后，新建项目弹窗立即可选（不刷新页面）', async ({ page }) => {
  await signIn(page)
  await page.goto('/styles')

  await expect(page.getByRole('heading', { name: '风格管理' })).toBeVisible()
  await page.getByRole('button', { name: '新增风格' }).click()

  const dialog = page.getByRole('dialog')
  // 默认表现形式是「现实」；这里显式选「动漫」，顺带覆盖拿到下拉变更
  await dialog.getByLabel('画面表现形式').selectOption('动漫')
  await dialog.getByLabel('风格名称').fill('赛博国风')
  await dialog.getByLabel('说明').fill('霓虹与水墨叠加，冷紫主调')
  await dialog.getByLabel('提示词质感描述').fill('霓虹与水墨叠加，冷紫主调，粒子与飞白结合')
  await dialog.getByRole('button', { name: '创建风格' }).click()

  await expect(page.getByText('赛博国风')).toBeVisible()

  // 用侧边栏做客户端跳转：整页刷新会清掉模块缓存，测不出失效逻辑
  await page.getByRole('link', { name: '项目' }).first().click()
  await page.getByRole('button', { name: '新建项目' }).click()

  const createDialog = page.getByRole('dialog')
  await createDialog.getByLabel('画面风格').selectOption('动漫')
  await expect(createDialog.getByLabel('剧集风格').locator('option', { hasText: '赛博国风' })).toHaveCount(1)
})

test('同组重名会被拒绝并提示', async ({ page }) => {
  await signIn(page)
  await page.goto('/styles')

  await page.getByRole('button', { name: '新增风格' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('风格名称').fill('真人都市')
  await dialog.getByRole('button', { name: '创建风格' }).click()

  await expect(dialog.getByText(/同组风格重名|已存在风格/)).toBeVisible()
})
