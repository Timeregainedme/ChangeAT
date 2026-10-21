import { expect, test, type Page } from '@playwright/test'

/**
 * 分镜工作室冒烟用例。
 *
 * 这一页是 6000+ 行的单文件，重构前必须先有回归网。
 * 用例只锁「页面能打开、能选镜头、能过滤」这三条最容易被结构改动打断的路径，
 * 不涉及生成类写操作（避免污染 mock 状态）。
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

const STUDIO_URL = '/projects/p1/chapters/c1/studio'

test('工作室三栏都能渲染', async ({ page }) => {
  await signIn(page)
  await page.goto(STUDIO_URL)

  await expect(page.getByText('分镜列表')).toBeVisible()
  await expect(page.getByText('主预览区')).toBeVisible()
  await expect(page.getByText('分镜生成面板')).toBeVisible()
  await expect(page.locator('.cs-shot-item').first()).toBeVisible()
})

test('点击镜头后预览区切换到该镜头', async ({ page }) => {
  await signIn(page)
  await page.goto(STUDIO_URL)

  const second = page.locator('.cs-shot-item').nth(1)
  await second.click()

  await expect(page.getByText(/当前分镜：02/)).toBeVisible()
})

test('切换到待确认筛选后只剩待确认镜头', async ({ page }) => {
  await signIn(page)
  await page.goto(STUDIO_URL)

  // 等列表真正加载完再统计，否则会量到加载中的 DOM
  await expect(page.locator('.cs-shot-item').first()).toBeVisible()
  await expect(page.locator('.cs-left .ant-segmented-item', { hasText: '全部' })).toBeVisible()

  const allCount = await page.locator('.cs-shot-item').count()
  await page.locator('.cs-left .ant-segmented-item', { hasText: '待确认' }).click()

  const pendingCount = await page.locator('.cs-shot-item').count()
  expect(pendingCount).toBeGreaterThan(0)
  expect(pendingCount).toBeLessThan(allCount)
  // 筛选后每一张卡片都应带「待确认」标记
  await expect(page.locator('.cs-shot-item').first()).toContainText('待确认')
})
