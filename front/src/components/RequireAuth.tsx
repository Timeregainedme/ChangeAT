/**
 * 路由守卫：未登录一律重定向到 /login，并把来源路径带过去以便登录后跳回。
 *
 * 首次进入时会用本地 token 向后端校验一次：
 * - 通过 → 刷新用户信息（账号可能被改名/停用）
 * - 401 → 清空本地会话并跳登录
 * - 网络错误 → 不清空 token（避免断网就掉登录），仅记录，放行到页面让业务请求自行报错
 */
import React, { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuthStore, type AuthUser } from '../store/useAuthStore'

interface MeEnvelope {
  code: number
  message: string
  data?: AuthUser
}

interface RequireAuthProps {
  children: React.ReactNode
}

const RequireAuth: React.FC<RequireAuthProps> = ({ children }) => {
  const location = useLocation()
  const token = useAuthStore((s) => s.token)
  const initialized = useAuthStore((s) => s.initialized)
  const clearSession = useAuthStore((s) => s.clearSession)
  const setUser = useAuthStore((s) => s.setUser)
  const markInitialized = useAuthStore((s) => s.markInitialized)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    if (initialized || !token) {
      if (!initialized && !token) markInitialized()
      return
    }

    let cancelled = false
    setChecking(true)

    void (async () => {
      try {
        const resp = await fetch('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (cancelled) return

        if (resp.status === 401) {
          clearSession()
          return
        }
        if (resp.ok) {
          const payload = (await resp.json()) as MeEnvelope
          if (payload.data) setUser(payload.data)
        }
        markInitialized()
      } catch {
        // 网络异常：保留 token，交给后续业务请求处理
        markInitialized()
      } finally {
        if (!cancelled) setChecking(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [initialized, token, clearSession, setUser, markInitialized])

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  if (!initialized || checking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spin size="large" tip="正在验证登录状态…" />
      </div>
    )
  }

  return <>{children}</>
}

export default RequireAuth