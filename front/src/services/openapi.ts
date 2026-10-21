import { OpenAPI } from './generated'
import { getStoredToken } from '../store/useAuthStore'

/**
 * 初始化由 OpenAPI 生成的请求客户端。
 *
 * 说明：
 * - 生成接口的路径已包含 `/api/v1/...`，因此 BASE 默认应为空串（同源）或完整后端地址。
 * - 本地开发默认直连 `http://localhost:8000`。
 */
export function initOpenAPI(base: string = '') {
  OpenAPI.BASE = base
}

const runtimeBackendUrl = window.__ENV?.BACKEND_URL
const buildtimeBackendUrl = import.meta.env.VITE_BACKEND_URL
const defaultBackendUrl = 'http://localhost:8000'

/**
 * mock 模式下强制走同源。
 *
 * public/env.js 在开发环境把 BACKEND_URL 指到 http://localhost:8000，
 * 请求就变成跨域；Service Worker 对跨域请求的接管不如同源稳定，
 * 实测会出现「MSW 已启用但请求仍然打到 8000 并连接失败」。
 * 同源 + MSW 拦截是唯一稳定的组合，也让 mock 与生产的路由行为一致。
 */
const useMock = import.meta.env.VITE_USE_MOCK === 'true'

initOpenAPI(useMock ? '' : runtimeBackendUrl ?? buildtimeBackendUrl ?? defaultBackendUrl)

/**
 * 每次请求动态读取 token（而非初始化时快照），
 * 这样登录/登出后无需重建客户端即可立即生效。
 */
OpenAPI.TOKEN = async () => getStoredToken() ?? ''
