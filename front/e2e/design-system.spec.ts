import { expect, test } from '@playwright/test'

/**
 * 设计系统冒烟用例。
 *
 * 选 /design 而不是业务页做第一条 e2e，是因为它不依赖登录态和后端接口：
 * 能独立验证「构建链路 + Tailwind token + 组件渲染」是否正常，
 * 后续业务链路的用例再叠加上来。
 */
test('设计系统预览页可渲染，主题可切换', async ({ page }) => {
  await page.goto('/design')

  await expect(page.getByRole('heading', { name: 'DyeingTime 设计系统' })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成参考图' })).toBeVisible()

  const html = page.locator('html')
  await expect(html).not.toHaveClass(/dark/)

  await page.getByRole('button', { name: '切换主题' }).click()
  await expect(html).toHaveClass(/dark/)

  await page.getByRole('button', { name: '切换主题' }).click()
  await expect(html).not.toHaveClass(/dark/)
})

test('侧滑面板可打开并关闭', async ({ page }) => {
  await page.goto('/design')

  await page.getByRole('button', { name: '打开侧滑面板' }).click()
  const sheetTitle = page.getByRole('dialog').getByText('镜头 5：雨夜对峙')
  await expect(sheetTitle).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(sheetTitle).toBeHidden()
})
