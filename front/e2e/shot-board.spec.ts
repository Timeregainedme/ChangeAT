import { expect, test, type Page } from '@playwright/test'

/**
 * 镜头看板用例（mock 数据）。
 *
 * 覆盖「看得懂」与「能动手」两件事：
 *   - 三个状态列都渲染，镜头按状态落位；
 *   - 全选后出现批量操作条，确认弹窗可开可取消。
 * 批量写操作的副作用不在 E2E 里验证（会污染 mock 状态），
 * 由后端契约与单元测试保证。
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

test('看板按状态分列并渲染镜头', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects/p1/chapters/c1/board')

  await expect(page.getByRole('heading', { name: /第1章/ })).toBeVisible()
  await expect(page.getByText(/镜头看板 · 共 \d+ 个镜头/)).toBeVisible()
  await expect(page.getByText('待确认', { exact: true })).toBeVisible()
  await expect(page.getByText('已就绪', { exact: true })).toBeVisible()
  await expect(page.getByText('远景：城郊老旧小区夜景')).toBeVisible()
})

test('全选后出现批量操作条，确认弹窗可取消', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects/p1/chapters/c1/board')
  await expect(page.getByText('远景：城郊老旧小区夜景')).toBeVisible()

  await page.getByRole('button', { name: '全选' }).first().click()
  await expect(page.getByText(/已选 \d+ 个镜头/)).toBeVisible()

  await page.getByRole('button', { name: '标记无需提取' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/标记为无需提取/)).toBeVisible()

  await dialog.getByRole('button', { name: '取消' }).click()
  await expect(dialog).toBeHidden()
  // 取消后选择保留（用户可以继续选别的），批量条仍在
  await expect(page.getByText(/已选 \d+ 个镜头/)).toBeVisible()
})

test('待确认列可发起批量确认，向导展示分组统计', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects/p1/chapters/c1/board')
  await expect(page.getByText(/镜头看板 · 共 \d+ 个镜头/)).toBeVisible()

  // 只选待确认列，确保批量确认按钮可用
  const pendingColumn = page.locator('section', { hasText: '待确认' }).first()
  await pendingColumn.getByRole('button', { name: '全选' }).click()
  await expect(page.getByText(/已选 \d+ 个镜头/)).toBeVisible()

  const confirmBtn = page.getByRole('button', { name: /批量确认/ })
  await expect(confirmBtn).toBeEnabled()
  await confirmBtn.click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/批量确认 \d+ 个镜头/)).toBeVisible()
  await expect(dialog.getByText('待确认对白')).toBeVisible()
  await expect(dialog.getByText('待确认资产')).toBeVisible()

  // 取消不应产生任何写入
  await dialog.getByRole('button', { name: '取消' }).click()
  await expect(dialog).toBeHidden()
})

test('从章节列表带 ?batch=confirm 进入时自动打开批量确认', async ({ page }) => {
  await signIn(page)
  await page.goto('/projects/p1/chapters/c1/board?batch=confirm')

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/批量确认 \d+ 个镜头/)).toBeVisible()

  // 参数只消费一次：关掉后地址栏不应还留着 batch=confirm
  await expect(page).not.toHaveURL(/batch=confirm/)

  await dialog.getByRole('button', { name: '取消' }).click()
  await expect(dialog).toBeHidden()
})
