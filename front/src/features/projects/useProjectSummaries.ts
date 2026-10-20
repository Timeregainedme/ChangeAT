import { useEffect, useState } from 'react'
import { StudioChaptersService } from '../../services/generated'
import type { ChapterRead, ChapterStatus } from '../../services/generated'
import { chapters as mockChapters } from '../../mocks/data'
import { getChapterPreparationState } from '../../pages/aiStudio/project/ProjectWorkbench/chapterPreparation'
import {
  loadProjectFlowStatsForChapters,
  type ProjectFlowStats,
} from '../../pages/aiStudio/project/ProjectWorkbench/projectFlowStats'
import type { ProjectView } from './types'

/** 章节摘要所需的字段子集，与分镜准备度判断函数的入参保持一致。 */
export interface ChapterInput {
  id: string
  projectId: string
  index: number
  title: string
  summary: string
  rawText: string
  storyboardCount: number
  status: ChapterStatus
  updatedAt: string
}

/**
 * 项目级摘要：当前应该做什么 + 镜头流量的三类计数。
 *
 * 为什么放在列表页算而不是让后端给：
 * 现阶段没有聚合接口，而这些信息决定「用户点进项目后第一步做什么」，
 * 比进度百分比更有用。等后端提供 board 聚合接口后，这里整体替换即可。
 */
export interface ProjectSummary {
  /** 章节准备态的 key：edit_raw / extract_shots / prepare_shots / shoot / create_first_chapter */
  stageKey: string
  stageText: string
  actionLabel: string
  hint: string
  chapterId?: string
  storyboardCount?: number
  /** 章节总数。后端 stats 可能为空，这里用实际拉到的章节数兜底。 */
  chapterCount: number
  flow: ProjectFlowStats | null
}

const useMock = import.meta.env.VITE_USE_MOCK === 'true'

/** 把后端章节对象转换成摘要函数的入参，集中处理字段名差异。 */
function toChapterInput(chapter: ChapterRead): ChapterInput {
  return {
    id: chapter.id,
    projectId: chapter.project_id,
    index: chapter.index,
    title: chapter.title,
    summary: chapter.summary ?? '',
    rawText: chapter.raw_text ?? '',
    storyboardCount: chapter.shot_count ?? chapter.storyboard_count ?? 0,
    status: chapter.status ?? 'draft',
    updatedAt: new Date().toISOString(),
  }
}

/**
 * 从一个项目的全部章节里挑出「最该先处理的那一章」。
 *
 * 顺序刻意固定为 录入原文 → 提取分镜 → 准备镜头 → 拍摄：
 * 这是主流程的真实先后关系，取第一个未完成阶段作为下一步建议。
 */
function summarizeProject(chapters: ChapterInput[]): ProjectSummary {
  const ordered = [...chapters].sort((a, b) => a.index - b.index)
  if (!ordered.length) {
    return {
      stageKey: 'create_first_chapter',
      stageText: '待创建章节',
      actionLabel: '创建第一章',
      hint: '项目还没有章节，先建第一章再拆镜头',
      chapterCount: 0,
      flow: null,
    }
  }

  const findByState = (key: string) =>
    ordered.find((chapter) => getChapterPreparationState(chapter).key === key)

  const chapter =
    findByState('edit_raw') ??
    findByState('extract_shots') ??
    findByState('prepare_shots') ??
    findByState('shoot') ??
    ordered[0]

  const state = getChapterPreparationState(chapter)
  return {
    stageKey: state.key,
    stageText: state.text,
    actionLabel: state.primaryAction,
    hint: `第${chapter.index}章 · ${state.hint}`,
    chapterId: chapter.id,
    storyboardCount: chapter.storyboardCount,
    chapterCount: ordered.length,
    flow: null,
  }
}

/**
 * 批量加载项目摘要。
 *
 * 每个项目要额外查章节与镜头流量，数量大时会打出较多请求，
 * 因此这里并发执行且整体失败时降级为空摘要（页面仍能正常浏览与进入项目），
 * 不因为「摘要拿不到」让整个列表变成错误页。
 */
export function useProjectSummaries(projects: ProjectView[]) {
  const [summaries, setSummaries] = useState<Record<string, ProjectSummary>>({})
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!projects.length) {
      setSummaries({})
      return
    }

    let cancelled = false
    setLoading(true)

    const load = async () => {
      try {
        const perProject = await Promise.all(
          projects.map(async (project) => {
            const chapters = useMock
              ? mockChapters
                  .filter((chapter) => chapter.projectId === project.id)
                  .map<ChapterInput>((chapter) => ({
                    id: chapter.id,
                    projectId: chapter.projectId,
                    index: chapter.index,
                    title: chapter.title,
                    summary: chapter.summary ?? '',
                    rawText: chapter.summary ?? '',
                    storyboardCount: chapter.storyboardCount,
                    status: chapter.status,
                    updatedAt: chapter.updatedAt,
                  }))
              : (
                  await StudioChaptersService.listChaptersApiV1StudioChaptersGet({
                    projectId: project.id,
                    page: 1,
                    pageSize: 100,
                  })
                ).data?.items?.map(toChapterInput) ?? []

            const summary = summarizeProject(chapters)

            // 镜头流量是「锦上添花」的信息：接口不可用时保留阶段摘要，
            // 不要因为流量统计失败把整张卡片降级成「待推进」。
            let flow: ProjectFlowStats | null = null
            if (chapters.length) {
              try {
                flow = await loadProjectFlowStatsForChapters(chapters)
              } catch {
                flow = null
              }
            }

            return [project.id, { ...summary, flow }] as const
          }),
        )

        if (!cancelled) setSummaries(Object.fromEntries(perProject))
      } catch {
        if (!cancelled) setSummaries({})
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [projects])

  return { summaries, loading }
}
