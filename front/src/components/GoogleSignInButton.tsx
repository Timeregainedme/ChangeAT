/**
 * Google 登录按钮（Google Identity Services）。
 *
 * 设计取舍：
 * - 用 GIS 官方按钮而不是自己画一个：品牌规范由 Google 维护，且能自动处理
 *   「不支持第三方 Cookie」「已是登录态」等边界场景。
 * - 只把 `credential`（ID Token）交给后端，前端不解析、不信任其中的用户信息，
 *   身份以服务端向 Google 校验的结果为准。
 * - 脚本按需加载（首次打开登录页才请求），不拖慢未使用 Google 登录的场景。
 */
import { useEffect, useRef, useState } from 'react'
import { Alert, Spin } from 'antd'

/** GIS 在 `window.google.accounts.id` 上暴露的最小 API 子集（只声明用到的部分）。 */
type GoogleIdentityServices = {
  initialize: (config: Record<string, unknown>) => void
  renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: GoogleIdentityServices
      }
    }
  }
}

const SCRIPT_ID = 'google-gsi-client'
const SCRIPT_SRC = 'https://accounts.google.com/gsi/client'

export type GoogleSignInButtonProps = {
  /** Google OAuth Client ID；为空表示未配置，组件不渲染 */
  clientId: string
  /** 拿到 ID Token 后的回调（由调用方提交给后端） */
  onCredential: (credential: string) => void
  disabled?: boolean
}

export function GoogleSignInButton({ clientId, onCredential, disabled }: GoogleSignInButtonProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  /** 用 ref 持有最新回调，避免父组件每次渲染都重新初始化 GIS（会重复渲染按钮）。 */
  const credentialHandlerRef = useRef(onCredential)
  useEffect(() => {
    credentialHandlerRef.current = onCredential
  }, [onCredential])

  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')

  useEffect(() => {
    if (!clientId) return
    let cancelled = false

    const init = () => {
      if (cancelled) return
      const gsi = window.google?.accounts?.id
      const container = containerRef.current
      if (!gsi || !container) {
        setStatus('error')
        return
      }
      gsi.initialize({
        client_id: clientId,
        // popup 模式：无需 redirect_uri，登录完成后直接把 credential 回调给页面。
        ux_mode: 'popup',
        auto_select: false,
        cancel_on_tap_outside: true,
        callback: (response: { credential?: string }) => {
          if (response?.credential) credentialHandlerRef.current(response.credential)
        },
      })
      container.innerHTML = ''
      gsi.renderButton(container, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        text: 'signin_with',
        shape: 'rectangular',
        logo_alignment: 'left',
        width: 320,
      })
      setStatus('ready')
    }

    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null
    if (existing) {
      if (window.google?.accounts?.id) {
        init()
      } else {
        setStatus('loading')
        existing.addEventListener('load', init)
        return () => {
          cancelled = true
          existing.removeEventListener('load', init)
        }
      }
    } else {
      setStatus('loading')
      const script = document.createElement('script')
      script.id = SCRIPT_ID
      script.src = SCRIPT_SRC
      script.async = true
      script.defer = true
      script.onload = init
      script.onerror = () => setStatus('error')
      document.head.appendChild(script)
    }

    return () => {
      cancelled = true
    }
  }, [clientId])

  if (!clientId) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Google 登录未配置"
        description="服务端未提供 GOOGLE_CLIENT_ID，暂不可用。"
      />
    )
  }

  return (
    <div className="w-full">
      {status === 'error' ? (
        <Alert
          type="error"
          showIcon
          message="Google 登录组件加载失败"
          description="可能是网络无法访问 accounts.google.com，或未在 Google 控制台配置当前域名。"
        />
      ) : (
        <div className="relative flex justify-center min-h-[44px]">
          {status !== 'ready' ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <Spin size="small" />
            </div>
          ) : null}
          {/* GIS 会在该容器内渲染官方按钮 */}
          <div ref={containerRef} aria-disabled={disabled} />
        </div>
      )}
    </div>
  )
}

export default GoogleSignInButton
