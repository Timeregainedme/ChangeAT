import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * 单测全局环境准备。
 *
 * 这里只放「所有用例都需要」的东西：
 *   - 每个用例后清理 DOM，避免上一个用例的节点影响断言；
 *   - 补 matchMedia，jsdom 没实现，而主题解析依赖它。
 * 业务相关的 mock（接口、路由）由各用例自行声明，不放这里，避免隐式耦合。
 */
afterEach(() => {
  cleanup()
})

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}
