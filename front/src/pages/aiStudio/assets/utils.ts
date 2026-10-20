import { OpenAPI } from '../../../services/generated'

function tryExtractFileIdFromUrl(value: string): string | null {
  try {
    const url = new URL(value)
    const m = url.pathname.match(/\/api\/v1\/studio\/files\/([^/]+)\/download\/?$/)
    if (m?.[1]) return decodeURIComponent(m[1])
  } catch {
    // ignore parse error
  }
  return null
}

export function resolveAssetUrl(value?: string | null): string | undefined {
  if (!value) return undefined
  const trimmed = value.trim()
  if (!trimmed) return undefined

  if (/^(?:[a-z][a-z\d+\-.]*:)?\/\//i.test(trimmed) || trimmed.startsWith('data:') || trimmed.startsWith('blob:')) {
    const fileId = tryExtractFileIdFromUrl(trimmed)
    if (fileId) return buildFileDownloadUrl(fileId)
    return trimmed
  }

  // 后端有些缩略图字段可能直接返回 file_id（不包含 / 或 :）。
  // 这种情况下需要拼接下载地址，否则 new URL 会生成错误路径。
  if (!trimmed.includes('/') && !trimmed.includes(':')) {
    return buildFileDownloadUrl(trimmed)
  }

  try {
    // 解析基准优先级：
    //   1. OpenAPI.BASE（由 initOpenAPI 设置；空串表示同源相对路径，必须保留而不能被兜底）
    //   2. window.__ENV.BACKEND_URL（nginx 运行时注入）
    //   3. 构建时 VITE_* 变量
    //   4. 最后才退回开发默认值
    // 注意：OpenAPI.BASE 为空串是「同源」的合法语义，不能用 || 兜底，
    // 否则会错误地指向 localhost:8000，导致缩略图与素材直链全部失效。
    const resolvedBase =
      OpenAPI.BASE ||
      window.__ENV?.BACKEND_URL ||
      import.meta.env.VITE_BACKEND_URL ||
      import.meta.env.VITE_API_BASE_URL ||
      ''

    // new URL 的第二个参数必须是绝对 URL 或同源相对基准；
    // 所以当 resolvedBase 为空时，直接用当前页面的 origin 作为基准。
    const base = resolvedBase || window.location.origin
    return new URL(trimmed, base).toString()
  } catch {
    return trimmed
  }
}

export function buildFileDownloadUrl(fileId?: string | null): string | undefined {
  if (!fileId) return undefined
  return resolveAssetUrl(`/api/v1/studio/files/${encodeURIComponent(fileId)}/download`)
}
