/**
 * 登录态管理。
 *
 * 设计取舍：
 * - token 存 localStorage：SPA 无 cookie 会话，刷新后需要保持登录。
 *   代价是 XSS 可窃取，因此后端不应回显敏感信息，且 CSP 应尽量收紧。
 * - 同时缓存用户信息，避免每次刷新都请求 /auth/me 造成首屏抖动；
 *   但仍会在后台校验一次，token 失效则自动清空。
 */
import { create } from 'zustand'

export interface AuthUser {
  id: number
  username: string
  display_name: string | null
  is_active: boolean
}

const TOKEN_KEY = 'dyeingtime_token'
const USER_KEY = 'dyeingtime_user'

/** 改名前的旧键：只在迁移时读取，迁移完成后立即删除。 */
const LEGACY_TOKEN_KEY = 'jellyfish_token'
const LEGACY_USER_KEY = 'jellyfish_user'

/**
 * 把旧品牌时期的登录态迁移到新键。
 *
 * 为什么必须迁移：改键名等于让所有已登录用户掉线，
 * 而 token 本身仍然有效，迁移成本极低、体验损失为零。
 * 迁移是幂等的：新键已有值时只清旧键，不覆盖。
 */
function migrateLegacySession(): void {
  try {
    const pairs: Array<[string, string]> = [
      [LEGACY_TOKEN_KEY, TOKEN_KEY],
      [LEGACY_USER_KEY, USER_KEY],
    ]
    for (const [legacy, next] of pairs) {
      const oldValue = window.localStorage.getItem(legacy)
      if (!oldValue) continue
      if (!window.localStorage.getItem(next)) {
        window.localStorage.setItem(next, oldValue)
      }
      window.localStorage.removeItem(legacy)
    }
  } catch {
    // 隐私模式等场景不可用：忽略即可，用户重新登录一次。
  }
}

migrateLegacySession()

function readToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function readUser(): AuthUser | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  /** 是否已完成首次「本地读取 + 服务端校验」，用于避免路由守卫误判 */
  initialized: boolean
  setSession: (token: string, user: AuthUser) => void
  clearSession: () => void
  setUser: (user: AuthUser) => void
  markInitialized: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: readToken(),
  user: readUser(),
  initialized: false,
  setSession: (token, user) => {
    try {
      window.localStorage.setItem(TOKEN_KEY, token)
      window.localStorage.setItem(USER_KEY, JSON.stringify(user))
    } catch {
      // 隐私模式等场景写入失败：仅保留内存态
    }
    set({ token, user, initialized: true })
  },
  clearSession: () => {
    try {
      window.localStorage.removeItem(TOKEN_KEY)
      window.localStorage.removeItem(USER_KEY)
    } catch {
      // ignore
    }
    set({ token: null, user: null, initialized: true })
  },
  setUser: (user) => {
    try {
      window.localStorage.setItem(USER_KEY, JSON.stringify(user))
    } catch {
      // ignore
    }
    set({ user })
  },
  markInitialized: () => set({ initialized: true }),
}))

/** 供非 React 环境（如 OpenAPI 客户端）读取 token。 */
export function getStoredToken(): string | null {
  return useAuthStore.getState().token
}