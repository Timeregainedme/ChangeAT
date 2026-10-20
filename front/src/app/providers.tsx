import { useEffect, type FC, type ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import * as Tooltip from '@radix-ui/react-tooltip'
import { queryClient } from '../lib/queryClient'
import { applyTheme, resolveTheme, useThemeStore, watchSystemTheme } from '../store/useThemeStore'

/**
 * 启动时同步一次主题，并订阅系统主题变化。
 *
 * 单独抽成组件而不是写进 store：store 在模块加载期就可能被 import，
 * 那时 DOM 还不一定就绪；挂在 React 生命周期里能保证只执行一次且时机正确。
 */
const ThemeBootstrap: FC = () => {
  useEffect(() => {
    const { mode } = useThemeStore.getState()
    applyTheme(resolveTheme(mode))
    return watchSystemTheme()
  }, [])

  return null
}

interface AppProvidersProps {
  children: ReactNode
}

/**
 * 全局 Provider 汇总。
 *
 * 存在的意义：新增一个全局能力（Query、Tooltip、Toast）时只改这一处，
 * 让 main.tsx 保持稳定，也避免将来出现「某个页面忘了包 Provider」的偶发 bug。
 */
export const AppProviders: FC<AppProvidersProps> = ({ children }) => (
  <QueryClientProvider client={queryClient}>
    <Tooltip.Provider delayDuration={200} skipDelayDuration={300}>
      <ThemeBootstrap />
      {children}
    </Tooltip.Provider>
  </QueryClientProvider>
)
