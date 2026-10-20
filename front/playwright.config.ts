import { defineConfig, devices } from '@playwright/test'

/**
 * 端到端测试配置。
 *
 * 端口与开发默认端口（7788）错开，避免本地正在开发时抢占端口导致测试假失败。
 * webServer 里显式设置 CI=1，让 vite.config 关闭自动打开浏览器：
 * 跑测试不该在开发机上弹出窗口。
 */
const PORT = 7799
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    // CI=1 关闭自动开浏览器；VITE_USE_MOCK 让 e2e 不依赖后端与真实登录
    env: { CI: '1', VITE_USE_MOCK: 'true' },
  },
})
