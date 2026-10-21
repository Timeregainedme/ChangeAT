import { useCallback, useEffect, useMemo, useState } from 'react'
import { StudioChaptersService, StudioShotsService } from '../../services/generated'
import type { ShotRead, ShotRuntimeSummaryRead } from '../../services/generated'

/** 运行时摘要里本页真正用到的字段，避免把整个生成态对象透传到 UI 层。 */
export interface ShotRuntimeState {
  hasActiveTasks: boolean
  activeTaskCount: number
}

/** 提取确认进度：决定这一镜能不能批量确认，以及确认前还差什么。 */
export interface ShotExtractionState {
  /** not_extracted 未提取 / extracted_pending 有待确认 / extracted_empty 无候选 / extracted_resolved 已确认 / skipped 已跳过 */
  state: 'not_extracted' | 'extracted_empty' | 'extracted_pending' | 'extracted_resolved' | 'skipped'
  pendingAssets: number
  pendingDialogues: number
}

/** 看板卡片用的镜头模型：业务字段 + 运行时状态 + 提取确认进度。 */
export interface BoardShot {
  id: string
  index: number
  title: string
  thumbnail?: string
  status: 'pending' | 'ready'
  skipExtraction: boolean
  scriptExcerpt: string
  runtime: ShotRuntimeState
  extraction: ShotExtractionState
}

/**
 * 镜头在「该做什么」维度上的归类。
 *
 * 这是把三类状态压成看板列的关键：运行中优先于确认状态，
 * 因为一个镜头正在生成时，用户不该再被提示「去确认信息」。
 */
export type BoardColumnKey = 'pending' | 'running' | 'ready'

export interface BoardChapter {
  id: string
  index: number
  title: string
}

const COLUMN_BY_STATE: Record<BoardColumnKey, string> = {
  pending: '待确认',
  running: '生成中',
  ready: '已就绪',
}

export { COLUMN_BY_STATE }

/** 把后端镜头对象收敛成看板模型。 */
function toBoardShot(shot: ShotRead, runtime?: ShotRuntimeSummaryRead): BoardShot {
  return {
    id: shot.id,
    index: shot.index,
    title: shot.title?.trim() || `镜头 ${shot.index}`,
    thumbnail: shot.thumbnail,
    status: shot.status === 'ready' ? 'ready' : 'pending',
    skipExtraction: Boolean(shot.skip_extraction),
    scriptExcerpt: shot.script_excerpt?.trim() ?? '',
    runtime: {
      hasActiveTasks: Boolean(runtime?.has_active_tasks),
      activeTaskCount: runtime?.active_task_count ?? 0,
    },
    extraction: {
      // 后端在列表里直接给出提取摘要，批量确认的「差什么」不需要再逐镜查一遍
      state: shot.extraction?.state ?? (shot.status === 'ready' ? 'extracted_resolved' : 'not_extracted'),
      pendingAssets: shot.extraction?.pending_asset_count ?? 0,
      pendingDialogues: shot.extraction?.pending_dialogue_count ?? 0,
    },
  }
}

/**
 * 判定镜头落在哪一列。
 *
 * 顺序写死为「运行中 → 已就绪 → 待确认」，与用户心智一致：
 * 先看有没有机器在干活，再看人工确认是否完成。
 */
export function getColumnOf(shot: BoardShot): BoardColumnKey {
  if (shot.runtime.hasActiveTasks) return 'running'
  if (shot.status === 'ready') return 'ready'
  return 'pending'
}

/**
 * 拉取章节下的全部镜头。
 *
 * 后端 page_size 上限是 100（超过会直接 422），所以按页拉取并拼接，
 * 而不是赌「一章不会超过 100 个镜头」——长章节加上配音/重绘确实可能超。
 * 上限 10 页是防御性兜底，避免后端分页参数异常时无限循环。
 */
async function loadAllShots(chapterId: string): Promise<ShotRead[]> {
  const all: ShotRead[] = []
  for (let page = 1; page <= 10; page += 1) {
    const res = await StudioShotsService.listShotsApiV1StudioShotsGet({
      chapterId,
      page,
      pageSize: 100,
      order: 'index',
      isDesc: false,
    })
    const items = res.data?.items ?? []
    all.push(...items)
    if (items.length < 100) break
  }
  return all
}

/**
 * 章节看板数据：镜头列表 + 运行时摘要 + 章节基础信息。
 *
 * 三个请求并发发出，其中章节信息只用于标题展示，失败时允许降级为空，
 * 不因为「拿不到章节名」让整个看板打不开。
 */
export function useChapterBoard(projectId?: string, chapterId?: string) {
  const [shots, setShots] = useState<BoardShot[]>([])
  const [chapter, setChapter] = useState<BoardChapter | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!chapterId) return
    setLoading(true)
    setError(null)
    try {
      const [boardShots, runtimeRes, chaptersRes] = await Promise.all([
        loadAllShots(chapterId),
        StudioShotsService.listShotRuntimeSummaryApiV1StudioShotsRuntimeSummaryGet({ chapterId }).catch(
          () => null,
        ),
        projectId
          ? StudioChaptersService.listChaptersApiV1StudioChaptersGet({
              projectId,
              page: 1,
              pageSize: 100,
            }).catch(() => null)
          : Promise.resolve(null),
      ])

      const runtimeMap = Object.fromEntries(
        (runtimeRes?.data ?? []).map((row) => [row.shot_id, row]),
      )
      setShots(boardShots.map((shot) => toBoardShot(shot, runtimeMap[shot.id])))

      const found = chaptersRes?.data?.items?.find((item) => item.id === chapterId)
      setChapter(found ? { id: found.id, index: found.index, title: found.title } : null)
    } catch {
      setShots([])
      setError('看板加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [chapterId, projectId])

  useEffect(() => {
    void load()
  }, [load])

  const grouped = useMemo(() => {
    const buckets: Record<BoardColumnKey, BoardShot[]> = { pending: [], running: [], ready: [] }
    for (const shot of shots) buckets[getColumnOf(shot)].push(shot)
    return buckets
  }, [shots])

  return { shots, grouped, chapter, loading, error, reload: load }
}
