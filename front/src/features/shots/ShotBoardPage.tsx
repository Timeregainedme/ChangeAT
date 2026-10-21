import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowUpRight, Clapperboard, Pencil, RefreshCw, Save } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { ScrollArea } from '../../components/ui/scroll-area'
import { Separator } from '../../components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '../../components/ui/sheet'
import { Skeleton } from '../../components/ui/skeleton'
import { Switch } from '../../components/ui/switch'
import { Textarea } from '../../components/ui/textarea'
import { cn } from '../../lib/utils'
import { StudioShotsService } from '../../services/generated'
import type { ShotUpdate, ShotVideoReadinessRead } from '../../services/generated'
import {
  getChapterShotEditPath,
  getChapterShotsPath,
  getChapterStudioPath,
} from '../../pages/aiStudio/project/ProjectWorkbench/routes'
import { getColumnOf, useChapterBoard, type BoardColumnKey, type BoardShot } from './useChapterBoard'

/** 三列的展示配置：颜色刻意来自三组不同 token，避免「一个颜色两种含义」。 */
const COLUMNS: { key: BoardColumnKey; label: string; dot: string; hint: string }[] = [
  { key: 'pending', label: '待确认', dot: 'bg-state-pending', hint: '还需要人工确认信息提取' },
  { key: 'running', label: '生成中', dot: 'bg-run-running', hint: '有任务正在跑，先等结果' },
  { key: 'ready', label: '已就绪', dot: 'bg-state-ready', hint: '信息已确认，可进入生成准备' },
]

/** 侧滑里可编辑的三个字段。序号、状态、关联文件不在看板里改，避免误操作。 */
interface ShotForm {
  title: string
  scriptExcerpt: string
  skipExtraction: boolean
}

function toForm(shot: BoardShot): ShotForm {
  return {
    title: shot.title,
    scriptExcerpt: shot.scriptExcerpt,
    skipExtraction: shot.skipExtraction,
  }
}

/**
 * 镜头卡片。
 *
 * 列表接口的 thumbnail 目前常为空，因此缩略图是「有则展示」而不是固定占位：
 * 固定 16:9 空盒子会让每张卡片高出 150px 却不携带任何信息，
 * 一屏看不到几个镜头。没有缩略图时直接收起图片区，让看板保持密度。
 */
function ShotCard({ shot, onOpen }: { shot: BoardShot; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group w-full overflow-hidden rounded-lg border border-border bg-card text-left transition-shadow hover:shadow-popover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {shot.thumbnail ? (
        <div className="aspect-video w-full overflow-hidden bg-muted">
          <img
            src={shot.thumbnail}
            alt={shot.title}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        </div>
      ) : null}

      <div className="space-y-1.5 p-3">
        <div className="flex items-center gap-1.5">
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            #{shot.index}
          </span>
          <p className="min-w-0 flex-1 truncate text-sm font-medium">{shot.title}</p>
          {shot.runtime.hasActiveTasks ? (
            <span className="shrink-0 rounded-full bg-run-running/15 px-1.5 py-0.5 text-[11px] text-run-running">
              {shot.runtime.activeTaskCount} 任务
            </span>
          ) : null}
        </div>

        <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
          {shot.scriptExcerpt || '暂无剧本摘录'}
        </p>

        {shot.skipExtraction ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60" />
            无需提取
          </span>
        ) : null}
      </div>
    </button>
  )
}

/**
 * 镜头看板页。
 *
 * 用三列替代表格，回答的是「这一章卡在哪」而不是「这一章有哪些字段」。
 * 拖动改状态暂不开放：状态推进依赖后端校验（提取、确认、生成条件），
 * 前端先做只读看板，避免用户拖出一个后端不认可的状态。
 *
 * 侧滑面板内可直接改标题、剧本摘录与「无需提取」开关：
 * 这三个字段是最常需要手工修的内容，留在看板里改可以少一次整页跳转。
 */
export function ShotBoardPage() {
  const { projectId, chapterId } = useParams<{ projectId: string; chapterId: string }>()
  const navigate = useNavigate()
  const { grouped, chapter, loading, error, reload, shots } = useChapterBoard(projectId, chapterId)

  // 用 id 而不是对象持有当前镜头：保存后会 reload，
  // 持对象会读到旧值，持 id 则能自动跟随最新数据。
  const [openShotId, setOpenShotId] = useState<string | null>(null)
  const activeShot = openShotId ? shots.find((shot) => shot.id === openShotId) ?? null : null

  const [form, setForm] = useState<ShotForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedHint, setSavedHint] = useState(false)

  const [readiness, setReadiness] = useState<ShotVideoReadinessRead | null>(null)
  const [readinessLoading, setReadinessLoading] = useState(false)

  // 打开时的初值只在切换镜头时取一次：reload 后 shots 引用会变，
  // 若把 form 绑到 shots 上，会把用户正在输入的内容冲掉。
  const shotsRef = useRef(shots)
  shotsRef.current = shots

  useEffect(() => {
    setSaveError(null)
    setSavedHint(false)
    if (!openShotId) {
      setForm(null)
      return
    }
    const shot = shotsRef.current.find((item) => item.id === openShotId)
    setForm(shot ? toForm(shot) : null)
  }, [openShotId])

  // 打开侧滑时按需拉取生成准备度：只在需要看清楚「能不能生成」时才查，
  // 避免在列表层给每个镜头都打一次请求。
  useEffect(() => {
    if (!openShotId) {
      setReadiness(null)
      return
    }
    let cancelled = false
    setReadinessLoading(true)
    StudioShotsService.getShotVideoReadinessApiApiV1StudioShotsShotIdVideoReadinessGet({
      shotId: openShotId,
    })
      .then((res) => {
        if (!cancelled) setReadiness(res.data ?? null)
      })
      .catch(() => {
        if (!cancelled) setReadiness(null)
      })
      .finally(() => {
        if (!cancelled) setReadinessLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [openShotId])

  const dirty =
    !!activeShot &&
    !!form &&
    (form.title.trim() !== activeShot.title ||
      form.scriptExcerpt !== activeShot.scriptExcerpt ||
      form.skipExtraction !== activeShot.skipExtraction)

  /**
   * 保存当前镜头。
   *
   * 只提交真正变化的字段：PATCH 语义是局部更新，把未改字段一起发回去
   * 会增加「另一个页面同时改了同一镜头」时的覆盖风险。
   */
  const saveShot = async () => {
    if (!activeShot || !form || !dirty) return
    if (!form.title.trim()) {
      setSaveError('镜头标题不能为空')
      return
    }

    const body: ShotUpdate = {}
    if (form.title.trim() !== activeShot.title) body.title = form.title.trim()
    if (form.scriptExcerpt !== activeShot.scriptExcerpt) body.script_excerpt = form.scriptExcerpt
    if (form.skipExtraction !== activeShot.skipExtraction) body.skip_extraction = form.skipExtraction

    setSaving(true)
    setSaveError(null)
    try {
      await StudioShotsService.updateShotApiV1StudioShotsShotIdPatch({
        shotId: activeShot.id,
        requestBody: body,
      })
      await reload()
      setSavedHint(true)
      window.setTimeout(() => setSavedHint(false), 2000)
    } catch {
      setSaveError('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const chapterLabel = chapter ? `第${chapter.index}章 · ${chapter.title}` : '章节'

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-6 py-4">
        <Button
          variant="ghost"
          size="icon"
          aria-label="返回项目"
          onClick={() => projectId && navigate(`/projects/${projectId}?tab=chapters`)}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold">{chapterLabel}</h1>
          <p className="truncate text-xs text-muted-foreground">
            镜头看板 · 共 {shots.length} 个镜头
          </p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void reload()} disabled={loading}>
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            刷新
          </Button>
          {projectId && chapterId ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(getChapterShotsPath(projectId, chapterId))}
              >
                列表视图
              </Button>
              <Button size="sm" onClick={() => navigate(getChapterStudioPath(projectId, chapterId))}>
                <Clapperboard className="h-3.5 w-3.5" />
                进入工作室
              </Button>
            </>
          ) : null}
        </div>
      </header>

      {error ? (
        <div className="mx-6 mt-4 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
        <div className="flex h-full min-w-[720px] gap-4 px-6 py-4">
          {COLUMNS.map((column) => {
            const items = grouped[column.key]
            return (
              <section
                key={column.key}
                className="flex h-full min-h-0 flex-1 basis-0 flex-col rounded-lg border border-border bg-muted/30"
              >
                <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
                  <span className={cn('h-2 w-2 rounded-full', column.dot)} />
                  <span className="text-sm font-medium">{column.label}</span>
                  <span className="rounded bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground">
                    {items.length}
                  </span>
                  <span className="ml-auto hidden truncate text-[11px] text-muted-foreground xl:inline">
                    {column.hint}
                  </span>
                </div>

                <ScrollArea className="min-h-0 flex-1">
                  <div className="space-y-3 p-3">
                    {loading
                      ? [0, 1, 2].map((i) => (
                          <div key={i} className="space-y-2 rounded-lg border border-border p-3">
                            <Skeleton className="h-4 w-1/3" />
                            <Skeleton className="h-4 w-2/3" />
                            <Skeleton className="h-3 w-full" />
                          </div>
                        ))
                      : items.map((shot) => (
                          <ShotCard key={shot.id} shot={shot} onOpen={() => setOpenShotId(shot.id)} />
                        ))}
                    {!loading && items.length === 0 ? (
                      <p className="px-1 py-6 text-center text-xs text-muted-foreground">
                        这一列没有镜头
                      </p>
                    ) : null}
                  </div>
                </ScrollArea>
              </section>
            )
          })}
        </div>
      </div>

      <Sheet
        open={openShotId !== null}
        onOpenChange={(open) => (open ? null : setOpenShotId(null))}
      >
        <SheetContent className="flex w-full flex-col sm:max-w-lg">
          {activeShot && form ? (
            <>
              <SheetHeader>
                <SheetTitle>
                  镜头 {activeShot.index}：{activeShot.title}
                </SheetTitle>
                <SheetDescription>
                  当前位于「{COLUMNS.find((c) => c.key === getColumnOf(activeShot))?.label}」
                </SheetDescription>
              </SheetHeader>

              <div className="mt-4 flex flex-1 flex-col gap-4 overflow-y-auto">
                {activeShot.thumbnail ? (
                  <div className="overflow-hidden rounded-lg border border-border">
                    <img src={activeShot.thumbnail} alt={activeShot.title} className="w-full" />
                  </div>
                ) : null}

                <div className="space-y-1.5">
                  <Label htmlFor="shot-title">镜头标题</Label>
                  <Input
                    id="shot-title"
                    value={form.title}
                    onChange={(event) =>
                      setForm((prev) => (prev ? { ...prev, title: event.target.value } : prev))
                    }
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="shot-script">剧本摘录</Label>
                  <Textarea
                    id="shot-script"
                    rows={5}
                    value={form.scriptExcerpt}
                    placeholder="这一镜在剧本里的原句，决定后续分镜与提示词的依据"
                    onChange={(event) =>
                      setForm((prev) =>
                        prev ? { ...prev, scriptExcerpt: event.target.value } : prev,
                      )
                    }
                  />
                </div>

                <div className="flex items-center justify-between rounded-md border border-border px-3 py-2.5">
                  <div>
                    <p className="text-sm font-medium">无需信息提取</p>
                    <p className="text-[11px] text-muted-foreground">
                      开启后不再要求该镜头做资产/对白确认
                    </p>
                  </div>
                  <Switch
                    checked={form.skipExtraction}
                    onCheckedChange={(checked) =>
                      setForm((prev) => (prev ? { ...prev, skipExtraction: checked } : prev))
                    }
                  />
                </div>

                <Separator />

                {/* 三类状态分开呈现：信息确认 / 运行时任务 / 视频生成准备度 */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">信息确认状态</span>
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-xs',
                        activeShot.status === 'ready'
                          ? 'bg-state-ready/15 text-state-ready'
                          : 'bg-state-pending/15 text-state-pending',
                      )}
                    >
                      {activeShot.skipExtraction
                        ? '无需提取'
                        : activeShot.status === 'ready'
                          ? '已确认'
                          : '待确认'}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">运行时任务</span>
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-xs',
                        activeShot.runtime.hasActiveTasks
                          ? 'bg-run-running/15 text-run-running'
                          : 'bg-run-idle/20 text-muted-foreground',
                      )}
                    >
                      {activeShot.runtime.hasActiveTasks
                        ? `${activeShot.runtime.activeTaskCount} 个进行中`
                        : '无运行中任务'}
                    </span>
                  </div>

                  <div className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">视频生成准备度</span>
                      {readinessLoading ? (
                        <span className="text-xs text-muted-foreground">检查中…</span>
                      ) : readiness ? (
                        <span
                          className={cn(
                            'rounded-full px-2 py-0.5 text-xs',
                            readiness.ready
                              ? 'bg-ready-complete/15 text-ready-complete'
                              : 'bg-ready-blocked/15 text-ready-blocked',
                          )}
                        >
                          {readiness.ready ? '可生成' : '缺条件'}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">暂无数据</span>
                      )}
                    </div>

                    {readiness?.checks?.length ? (
                      <ul className="mt-2 space-y-1">
                        {readiness.checks.map((check) => (
                          <li key={check.key} className="flex items-start gap-2 text-xs">
                            <span
                              className={cn(
                                'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                                check.ok ? 'bg-ready-complete' : 'bg-ready-blocked',
                              )}
                            />
                            <span className="text-muted-foreground">{check.message}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </div>

                {saveError ? (
                  <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {saveError}
                  </p>
                ) : null}
              </div>

              <div className="mt-4 flex shrink-0 items-center gap-2 border-t border-border pt-3">
                <Button onClick={saveShot} disabled={!dirty || saving} className="flex-1">
                  <Save className="h-3.5 w-3.5" />
                  {saving ? '保存中…' : savedHint ? '已保存' : '保存修改'}
                </Button>
                {projectId && chapterId ? (
                  <>
                    <Button
                      variant="outline"
                      size="icon"
                      aria-label="打开完整编辑页"
                      onClick={() =>
                        navigate(getChapterShotEditPath(projectId, chapterId, activeShot.id))
                      }
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={() => navigate(getChapterStudioPath(projectId, chapterId))}
                    >
                      <ArrowUpRight className="h-3.5 w-3.5" />
                      去生成
                    </Button>
                  </>
                ) : null}
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** 供卡片组件复用的导出，便于后续在看板内做内联操作。 */
export { ShotCard }

export default ShotBoardPage
