/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string
  readonly VITE_BACKEND_URL?: string
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  /** 运行时注入的配置（由 nginx 生成 /env.js，部署时无需重新构建前端） */
  __ENV?: {
    BACKEND_URL?: string
    GOOGLE_CLIENT_ID?: string
  }
}
