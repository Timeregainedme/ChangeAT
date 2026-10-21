import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import App from './App.tsx'
import 'antd/dist/reset.css'
import './index.css'
import './i18n'
import './services/openapi'
import { useAppStore } from './store/useAppStore'
import { useThemeStore } from './store/useThemeStore'
import { AppProviders } from './app/providers'

const RootApp: React.FC = () => {
  const language = useAppStore((state) => state.language)
  const resolvedTheme = useThemeStore((state) => state.resolved)
  const antdLocale = language === 'en-US' ? enUS : zhCN

  const antdThemeConfig = React.useMemo(
    () => ({
      algorithm:
        resolvedTheme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      token: {
        colorPrimary: resolvedTheme === 'dark' ? '#8b7cf8' : '#5f3bed',
        borderRadius: 8,
      },
    }),
    [resolvedTheme],
  )

  /**
   * 同步全局主题给 antd 的静态方法。
   *
   * message / notification / Modal.confirm 使用独立的 React 根渲染，
   * 读的是 ConfigProvider.config 设置的全局 theme 而不是组件树里的 context。
   * 不同步这一层，深色模式下会弹出白色的提示条与确认框。
   */
  React.useEffect(() => {
    ConfigProvider.config({ theme: antdThemeConfig })
  }, [antdThemeConfig])

  return (
    <ConfigProvider
      locale={antdLocale}
      /**
       * antd 跟随设计系统的深浅主题。
       *
       * 存量页面里仍有硬编码的 Tailwind 浅色类（bg-white / text-gray-500 等），
       * 只切 antd 算法会留下「深色表格 + 白色卡片」的割裂，因此同时用
       * index.css 里的 `.dark` 补丁把常用浅色工具类重映射到语义 token。
       * 两套一起生效，存量页面才能整体进入深色。
       */
      theme={antdThemeConfig}
    >
      <AppProviders>
        <App />
      </AppProviders>
    </ConfigProvider>
  )
}

class AppErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return (
        <div style={{ padding: 24, fontFamily: 'sans-serif' }}>
          <h2>页面加载出错</h2>
          <pre style={{ color: '#c00', overflow: 'auto' }}>
            {this.state.error.message}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}

function renderApp() {
  const root = document.getElementById('root')
  if (!root) return
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <AppErrorBoundary>
        <RootApp />
      </AppErrorBoundary>
    </React.StrictMode>,
  )
}


async function enableMocking() {
  // 必须用 import.meta.env.DEV 收口：Vite 在 production build 时会把
  // `import.meta.env.DEV` 静态替换为 false，整个分支连同动态 import 一起被
  // tree-shake 掉。若只用 VITE_USE_MOCK 判断，msw 与 handlers 仍会被打包成
  // 一个 ~286KB 的 chunk（首屏不加载但白白增大产物体积、拖慢构建与部署）。
  if (!import.meta.env.DEV || import.meta.env.VITE_USE_MOCK !== 'true') {
    return
  }
  try {
    const { worker } = await import('./mocks/browser')
    await worker.start({ onUnhandledRequest: 'bypass' })
  } catch (error) {
    console.error('MSW start failed:', error)
  }
}

/**
 * 启动顺序。
 *
 * 非 mock 环境立即渲染，避免任何启动等待拖慢首屏；
 * mock 环境必须先等 Service Worker 就绪再渲染——否则首屏那批请求会在
 * worker 接管前发出去，直接打到不存在的后端（localhost:8000 连接拒绝），
 * 页面表现为「数据加载失败」。这类失败在 E2E 里表现得尤其不稳定。
 */
async function bootstrap() {
  if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCK === 'true') {
    await enableMocking()
  }
  renderApp()
}

void bootstrap()

