import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 主题偏好：跟随系统 / 强制浅色 / 强制深色。 */
export type ThemeMode = 'system' | 'light' | 'dark'
/** 实际生效的主题，由偏好解析得到，不会等于 'system'。 */
export type ResolvedTheme = 'light' | 'dark'

interface ThemeState {
  mode: ThemeMode
  resolved: ResolvedTheme
  setMode: (mode: ThemeMode) => void
  /** 在浅色 / 深色之间一键切换（跟随系统时以当前实际值为基准取反）。 */
  toggle: () => void
}

const STORAGE_KEY = 'dyeingtime-theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

/**
 * 把偏好解析成实际主题。
 *
 * 抽成纯函数是为了让「系统主题变化」和「用户手动切换」走同一条判断路径，
 * 避免两处逻辑各写一遍后行为不一致。
 */
export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') {
    if (typeof window === 'undefined' || !window.matchMedia) return 'light'
    return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
  }
  return mode
}

/**
 * 将主题写到 <html> 上。
 *
 * 用 class 而不是 CSS 媒体查询：用户手动选择必须能覆盖系统偏好，
 * 而 Tailwind 的 darkMode: ['class'] 就是按这个 class 生效的。
 */
export function applyTheme(resolved: ResolvedTheme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
}

/**
 * 主题状态。
 *
 * 为什么放在 Zustand 而不是 Context：主题切换是低频但全局读取的状态，
 * 放 store 可以避免 Provider 重渲染整棵树，也方便非 React 代码（如测试）直接读取。
 */
export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: 'system',
      resolved: 'light',
      setMode: (mode) => {
        const resolved = resolveTheme(mode)
        applyTheme(resolved)
        set({ mode, resolved })
      },
      toggle: () => {
        const next: ResolvedTheme = get().resolved === 'dark' ? 'light' : 'dark'
        applyTheme(next)
        set({ mode: next, resolved: next })
      },
    }),
    {
      name: STORAGE_KEY,
      // 只持久化偏好，resolved 每次启动按当前系统重新解析
      partialize: (state) => ({ mode: state.mode }),
      onRehydrateStorage: () => (state) => {
        if (!state) return
        const resolved = resolveTheme(state.mode)
        applyTheme(resolved)
        state.resolved = resolved
      },
    },
  ),
)

/**
 * 订阅系统主题变化。
 *
 * 只在 mode === 'system' 时才跟随；用户显式选过浅色/深色就不该被系统设置改回去。
 * 返回取消订阅函数，调用方负责在组件卸载时清理。
 */
export function watchSystemTheme(): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const media = window.matchMedia(DARK_QUERY)

  const handler = () => {
    const state = useThemeStore.getState()
    if (state.mode !== 'system') return
    const resolved = resolveTheme('system')
    applyTheme(resolved)
    useThemeStore.setState({ resolved })
  }

  media.addEventListener('change', handler)
  return () => media.removeEventListener('change', handler)
}
