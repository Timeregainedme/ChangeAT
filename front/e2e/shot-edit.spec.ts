import { expect, test, type Page } from '@playwright/test'

/**
 * 分镜编辑页回归用例。
 *
 * 这一页是整个「准备」流程的核心工作台（近 1900 行、状态与异步任务最多），
 * 任何重构都必须先有回归网。用例刻意只锁「加载与导航」这两条最容易被改坏的路径：
 *   - 直接打开某个镜头，不会被重定向回列表；
 *   - 左侧切换镜头会换 URL 并刷新右侧编辑区；
 *   - 基础信息与提取确认两个 tab 都渲染。
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

const EDIT_URL = '/projects/p1/chapters/c1/shots/s2/edit'

test('直接打开镜头编辑页，停留在编辑页并回填标题', async ({ page }) => {
  await signIn(page)
  await page.goto(EDIT_URL)

  await expect(page).toHaveURL(new RegExp('/shots/s2/edit$'))
  await expect(page.getByText('分镜准备与信息确认')).toBeVisible()

  // 有待确认项时默认落在「提取确认」，把用户直接放到该做的事上
  await expect(page.getByRole('tab', { name: /提取确认/ })).toHaveAttribute('aria-selected', 'true')

  await page.getByRole('tab', { name: /基础信息/ }).click()
  await expect(page.getByRole('textbox').first()).toHaveValue('中景：出租屋内静止的风扇')
})

test('基础信息与提取确认两个 tab 都能渲染', async ({ page }) => {
  await signIn(page)
  await page.goto(EDIT_URL)

  await expect(page.getByRole('tab', { name: /基础信息/ })).toBeVisible()
  await page.getByRole('tab', { name: /提取确认/ }).click()
  await expect(page.getByRole('tab', { name: /提取确认/ })).toHaveAttribute('aria-selected', 'true')
})

test('左侧切镜头会更新 URL 与编辑区标题', async ({ page }) => {
  await signIn(page)
  await page.goto(EDIT_URL)
  await page.getByRole('tab', { name: /基础信息/ }).click()
  await expect(page.getByRole('textbox').first()).toHaveValue('中景：出租屋内静止的风扇')

  await page.getByText('#3 · 近景：两人对峙的沉默').click()

  await expect(page).toHaveURL(/\/shots\/s3\/edit$/)
  await page.getByRole('tab', { name: /基础信息/ }).click()
  await expect(page.getByRole('textbox').first()).toHaveValue('近景：两人对峙的沉默')
})
