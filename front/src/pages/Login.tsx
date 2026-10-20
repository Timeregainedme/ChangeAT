/**
 * 登录页。
 *
 * 说明：
 * - 直接调用 fetch 而非 OpenAPI 生成客户端：登录接口不需要携带 token，
 *   且此处独立于业务客户端，避免「未登录时客户端自动跳转」造成循环。
 * - 成功后写入 useAuthStore 并跳回来源页（location.state.from）或项目列表。
 */
import React, { useState } from 'react'
import { Button, Card, Divider, Form, Input, Typography, message } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore, type AuthUser } from '../store/useAuthStore'
import { GoogleSignInButton } from '../components/GoogleSignInButton'

const { Title, Text } = Typography

/** 登录接口的响应信封（与后端 ApiResponse 对齐）。 */
interface LoginEnvelope {
  code: number
  message: string
  data?: {
    access_token: string
    token_type: string
    expires_in: number
    user: AuthUser
  }
}

interface LocationState {
  from?: string
}

const Login: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const setSession = useAuthStore((s) => s.setSession)
  const [submitting, setSubmitting] = useState(false)
  /** Google 登录请求进行中（与账号密码登录分开，避免互相锁按钮） */
  const [googleSubmitting, setGoogleSubmitting] = useState(false)
  const [form] = Form.useForm<{ username: string; password: string }>()

  /** Google OAuth Client ID 来自运行时注入的 env.js，改配置不需要重新构建前端。 */
  const googleClientId = (window.__ENV?.GOOGLE_CLIENT_ID ?? '').trim()

  const from = (location.state as LocationState | null)?.from || '/projects'

  const handleSubmit = async (values: { username: string; password: string }) => {
    setSubmitting(true)
    try {
      const resp = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: values.username, password: values.password }),
      })

      // 后端错误也是 JSON 信封；解析失败时退化为状态码提示
      let payload: LoginEnvelope | null = null
      try {
        payload = (await resp.json()) as LoginEnvelope
      } catch {
        payload = null
      }

      if (!resp.ok || !payload?.data?.access_token) {
        const detail = (payload as unknown as { detail?: string } | null)?.detail
        message.error(detail || payload?.message || `登录失败（HTTP ${resp.status}）`)
        return
      }

      completeLogin(payload.data.access_token, payload.data.user)
    } catch (error) {
      message.error(error instanceof Error ? `无法连接服务：${error.message}` : '登录请求失败')
    } finally {
      setSubmitting(false)
    }
  }

  /** 登录成功后的统一收尾：写入会话、提示、按来源页跳转。 */
  const completeLogin = (token: string, user: AuthUser) => {
    setSession(token, user)
    message.success('登录成功')
    navigate(from, { replace: true })
  }

  /**
   * Google 登录：把 GIS 返回的 ID Token 交给后端校验。
   *
   * 前端不解析 token 内容——身份完全以服务端向 Google 校验的结果为准，
   * 这样即使有人篡改请求体也无法伪造邮箱。
   */
  const handleGoogleCredential = async (credential: string) => {
    setGoogleSubmitting(true)
    try {
      const resp = await fetch('/api/v1/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      })
      let payload: LoginEnvelope | null = null
      try {
        payload = (await resp.json()) as LoginEnvelope
      } catch {
        payload = null
      }
      if (!resp.ok || !payload?.data?.access_token) {
        const detail = (payload as unknown as { detail?: string } | null)?.detail
        message.error(detail || payload?.message || `Google 登录失败（HTTP ${resp.status}）`)
        return
      }
      completeLogin(payload.data.access_token, payload.data.user)
    } catch (error) {
      message.error(error instanceof Error ? `无法连接服务：${error.message}` : 'Google 登录请求失败')
    } finally {
      setGoogleSubmitting(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ background: 'linear-gradient(135deg, #eef2f7 0%, #e3ecf7 100%)' }}
    >
      <Card style={{ width: 400, boxShadow: '0 8px 32px rgba(0,0,0,0.08)' }}>
        <div className="text-center mb-6">
          <img src="/logo.png" alt="DyeingTime" className="w-14 h-14 mx-auto mb-3" />
          <Title level={3} style={{ marginBottom: 4 }}>
            DyeingTime
          </Title>
          <Text type="secondary">AI 短剧工厂 · 请登录</Text>
        </div>

        <Form form={form} layout="vertical" onFinish={handleSubmit} autoComplete="on" requiredMark={false}>
          <Form.Item
            label="账号"
            name="username"
            rules={[{ required: true, message: '请输入账号' }]}
          >
            <Input
              size="large"
              prefix={<UserOutlined />}
              placeholder="账号"
              autoComplete="username"
              autoFocus
            />
          </Form.Item>

          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="密码"
              autoComplete="current-password"
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
              登录
            </Button>
          </Form.Item>
        </Form>

        {googleClientId ? (
          <>
            <Divider plain className="!text-xs !text-gray-400">
              或
            </Divider>
            {googleSubmitting ? (
              <div className="text-center text-sm text-gray-500">正在验证 Google 账号…</div>
            ) : (
              <GoogleSignInButton
                clientId={googleClientId}
                onCredential={(credential) => void handleGoogleCredential(credential)}
                disabled={submitting}
              />
            )}
          </>
        ) : null}
      </Card>
    </div>
  )
}

export default Login