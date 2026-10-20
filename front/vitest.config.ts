import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * 单元测试配置。
 *
 * 单独一份而不是塞进 vite.config.ts：测试专用的 jsdom 环境与 setup 文件
 * 不应影响生产构建配置，分开后改测试不会牵动部署。
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // 只跑 src 下的单测，e2e 目录交给 Playwright，避免两套 runner 互相抓用例
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
  },
})
