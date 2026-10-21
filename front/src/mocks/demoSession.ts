/**
 * 演示会话（仅 mock 模式使用）。
 *
 * 目的：不启动后端也能直接进入应用和原型页。
 * RequireAuth 只校验「本地有没有 token」，随后用 /auth/me 复核；
 * mock 里已经返回了演示账号，所以这里只需要预置一份 token/user。
 *
 * 不做的事：不覆盖已有会话。开发者如果在同浏览器里登录过真实环境，
 * 保留真实 token 更符合预期（切到 mock 脚本时再看接口报错即可）。
 */
const TOKEN_KEY = 'dyeingtime_token'
const USER_KEY = 'dyeingtime_user'

const DEMO_TOKEN = 'mock-demo-token'
const DEMO_USER = {
  id: 1,
  username: 'demo',
  display_name: '演示账号',
}

/**
 * 预置演示会话；已有 token 时保持原样。
 *
 * 注意要同时写进 store：auth store 在模块加载时就把 localStorage 读进内存了，
 * 只写 localStorage 不会让当前这次渲染看到 token（表现是一直停在登录页）。
 */
export async function ensureDemoSession(): Promise<void> {
  if (typeof window === 'undefined') return

  let token = DEMO_TOKEN
  let user = DEMO_USER

  try {
    const storedToken = window.localStorage.getItem(TOKEN_KEY)
    const storedUser = window.localStorage.getItem(USER_KEY)
    if (storedToken) token = storedToken
    if (storedUser) user = JSON.parse(storedUser) as typeof DEMO_USER

    if (!storedToken) window.localStorage.setItem(TOKEN_KEY, token)
    if (!storedUser) window.localStorage.setItem(USER_KEY, JSON.stringify(user))

    // 演示模式默认中文：浏览器语言为英文时会让原型页显示英文，和文档/截图对不上
    if (!window.localStorage.getItem('dyeingtime_language')) {
      window.localStorage.setItem('dyeingtime_language', 'zh-CN')
    }
  } catch {
    // 隐私模式等写不进去时忽略：RequireAuth 会退回登录页，不影响其他功能
  }

  const { useAuthStore } = await import('../store/useAuthStore')
  useAuthStore.setState({ token, user: user as never, initialized: true })
}
