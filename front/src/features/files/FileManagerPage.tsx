import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, FileAudio, FileImage, FileVideo, RefreshCw, Search } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { cn } from '../../lib/utils'
import { StudioFilesService } from '../../services/generated'
import type { FileRead } from '../../services/generated'
import { buildFileDownloadUrl, resolveAssetUrl } from '../../pages/aiStudio/assets/utils'

const PAGE_SIZE = 24

type TypeFilter = 'all' | 'video' | 'image' | 'audio'

const TYPE_LABEL: Record<TypeFilter, string> = {
  all: '全部',
  video: '视频',
  image: '图片',
  audio: '音频',
}

/** 类型徽标：用图标 + 中文，避免直接展示 image/video 这类枚举值。 */
function TypeIcon({ type }: { type: string }) {
  if (type === 'video') return <FileVideo className="h-3.5 w-3.5" />
  if (type === 'audio') return <FileAudio className="h-3.5 w-3.5" />
  return <FileImage className="h-3.5 w-3.5" />
}

/**
 * 全局文件管理页。
 *
 * 之前项目工作台里的「前往文件管理」指向 /files，但路由根本不存在，点了就是 404。
 * 这里把它补成真实页面：跨项目查看所有素材，按类型与关键字过滤，直接下载。
 *
 * 分页走服务端（后端 page_size 上限 100），类型过滤在前端做——
 * 文件类型是有限枚举，先取一页再过滤比逐类型请求更省往返；
 * 需要跨页精确过滤时再让后端加 type 参数。
 */
export function FileManagerPage() {
  const [files, setFiles] = useState<FileRead[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await StudioFilesService.listFilesApiApiV1StudioFilesGet({
        q: keyword.trim() || undefined,
        page,
        pageSize: PAGE_SIZE,
        order: 'updated_at',
        isDesc: true,
      })
      setFiles(res.data?.items ?? [])
      setTotal(res.data?.pagination?.total ?? 0)
    } catch {
      setFiles([])
      setError('文件列表加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [keyword, page])

  useEffect(() => {
    void load()
  }, [load])

  // 改关键字时回到第一页，避免停在越界页看不到结果
  useEffect(() => {
    setPage(1)
  }, [keyword])

  const visible = useMemo(
    () => (typeFilter === 'all' ? files : files.filter((f) => f.type === typeFilter)),
    [files, typeFilter],
  )

  const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="shrink-0 border-b border-border px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">文件管理</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              所有项目生成的图片、视频与音频；下载即取原始文件
            </p>
          </div>
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
            刷新
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索文件名"
              className="pl-8"
            />
          </div>
          <Select
            value={typeFilter}
            aria-label="文件类型"
            className="w-28"
            onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}
          >
            {(Object.keys(TYPE_LABEL) as TypeFilter[]).map((key) => (
              <option key={key} value={key}>
                {TYPE_LABEL[key]}
              </option>
            ))}
          </Select>
          <span className="ml-auto text-xs text-muted-foreground">共 {total} 个文件</span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        {error ? (
          <div className="mb-4 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="space-y-2 rounded-lg border border-border p-3">
                <Skeleton className="aspect-video w-full" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ))}
          </div>
        ) : visible.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <p>{files.length === 0 ? '还没有任何文件' : '当前类型下没有文件'}</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
            {visible.map((file) => {
              const thumb = resolveAssetUrl(file.thumbnail)
              return (
                <div
                  key={file.id}
                  className="group overflow-hidden rounded-lg border border-border bg-card transition-shadow hover:shadow-popover"
                >
                  <div className="relative aspect-video w-full overflow-hidden bg-muted">
                    {thumb && file.type === 'image' ? (
                      <img src={thumb} alt={file.name} loading="lazy" className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                        <TypeIcon type={file.type} />
                      </div>
                    )}
                    <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">
                      <TypeIcon type={file.type} />
                      {TYPE_LABEL[(file.type as TypeFilter) ?? 'all'] ?? file.type}
                    </span>
                  </div>

                  <div className="space-y-2 p-3">
                    <p className="truncate text-sm font-medium" title={file.name}>
                      {file.name}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="truncate text-[11px] text-muted-foreground">
                        {file.tags?.length ? file.tags.join(' · ') : '无标签'}
                      </span>
                      <a
                        href={buildFileDownloadUrl(file.id)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-primary hover:bg-accent"
                      >
                        <Download className="h-3.5 w-3.5" />
                        下载
                      </a>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {maxPage > 1 ? (
          <div className="mt-5 flex items-center justify-center gap-2 text-sm">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((prev) => Math.max(1, prev - 1))}
            >
              上一页
            </Button>
            <span className="text-muted-foreground">
              {page} / {maxPage}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= maxPage || loading}
              onClick={() => setPage((prev) => Math.min(maxPage, prev + 1))}
            >
              下一页
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default FileManagerPage
