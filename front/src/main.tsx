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
import { AppProviders } from './app/providers'

const RootApp: React.FC = () => {
  const language = useAppStore((state) => state.language)
  const antdLocale = language === 'en-US' ? enUS : zhCN

  return (
    <ConfigProvider
      locale={antdLocale}
      /**
       * antd 主题保持浅色算法，不跟随深色主题。
       *
       * 原因：存量 antd 页面里仍有大量硬编码的浅色背景（bg-white / 浅灰渐变），
       * 只切 antd 算法会得到「深色表格 + 白色卡片」的半深半浅状态，比全浅更难读。
       * 迁移策略改为：外壳与新页面支持深浅主题，存量页面固定浅色画布，
       * 每迁完一页，可跟随主题的面积就增加一块，直到 antd 整体移除。
       */
      theme={{
        algorithm: antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: '#5f3bed',
          borderRadius: 8,
        },
      }}
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

// 先立即渲染，避免 MSW 启动阻塞导致白屏
renderApp()

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

void enableMocking()

