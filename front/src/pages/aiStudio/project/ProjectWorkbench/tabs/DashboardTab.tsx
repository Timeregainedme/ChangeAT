import { Card, Button, Spin } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileSearchOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { TabKey } from '../constants'
import {
  getChapterBoardPath,
  getChapterShotsPath,
  getProjectChaptersPath,
} from '../routes'
import { useProject, useChapters } from '../hooks/useProjectData'
import { ensureHasShotsBeforeShooting } from '../ensureHasShotsBeforeShooting'
import { getChapterPreparationState } from '../chapterPreparation'
import { loadProjectFlowStatsForChapters, type ProjectFlowStats } from '../projectFlowStats'

/**
 * 项目工作台的仪表盘。
 *
 * 重写原则：**一屏只回答三个问题**——现在该做什么、流程走到哪、还剩什么没做。
 *   - 去掉了「当前推荐动作 / 当前待办 / 统计卡片」三处互相重复的入口；
 *   - 去掉了资产卡片里写死的 80/60/75 假进度条：那是装饰，不是数据，
 *     用户会把它当成真实完成度；
 *   - 阶段卡片改为直接跳到该阶段最该处理的那一章，而不是统一跳回章节列表。
 */
export function DashboardTab({ onSelectTab }: { onSelectTab: (tab: TabKey) => void }) {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const { project, loading: projectLoading } = useProject(projectId)
  const { chapters, loading: chaptersLoading } = useChapters(projectId)

  const [flowStats, setFlowStats] = useState<ProjectFlowStats>({
    totalShots: 0,
    pendingConfirmShots: 0,
    readyShots: 0,
    generatingShots: 0,
  })
  const [flowStatsLoading, setFlowStatsLoading] = useState(false)

  const loading = projectLoading || chaptersLoading
  const chaptersByIndex = [...chapters].sort((a, b) => a.index - b.index)

  /** 按推进顺序找第一个还没完成的章节，作为「下一步」。 */
  const recommendedChapter =
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'edit_raw') ??
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'extract_shots') ??
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'prepare_shots') ??
    chaptersByIndex.find((chapter) => getChapterPreparationState(chapter).key === 'shoot') ??
    chaptersByIndex[0] ??
    null

  const recommendedState = recommendedChapter ? getChapterPreparationState(recommendedChapter) : null

  // 有分镜后，下一步先去看看哪些镜头没准备好，而不是直接进工作室。
  // 文案必须跟着跳转目标一起改，否则会出现「写着工作室、其实打开看板」。
  const recommendedActionLabel =
    recommendedState?.key === 'prepare_shots'
      ? '查看镜头看板'
      : (recommendedState?.primaryAction ?? '创建第一章')

  useEffect(() => {
    let cancelled = false
    if (!projectId || !chapters.length) {
      setFlowStats({ totalShots: 0, pendingConfirmShots: 0, readyShots: 0, generatingShots: 0 })
      return () => {
        cancelled = true
      }
    }

    setFlowStatsLoading(true)
    void loadProjectFlowStatsForChapters(chapters)
      .then((stats) => {
        if (!cancelled) setFlowStats(stats)
      })
      .catch(() => {
        // 统计失败不影响主流程：保留 0，页面仍可正常使用
        if (!cancelled) {
          setFlowStats({ totalShots: 0, pendingConfirmShots: 0, readyShots: 0, generatingShots: 0 })
        }
      })
      .finally(() => {
        if (!cancelled) setFlowStatsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [chapters, projectId])

  if (loading && !project) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }
  if (!project) return null

  /**
   * 跳到某个阶段最该处理的那一章。
   *
   * 四个阶段分别落在不同页面（章节编辑 / 分镜列表 / 镜头看板 / 工作室），
   * 由这里统一分派，避免每个入口各写一份跳转逻辑。
   */
  const jumpToStage = (stageKey: string) => {
    if (!projectId) return
    const chapter = chaptersByIndex.find((item) => getChapterPreparationState(item).key === stageKey)
    if (!chapter) {
      onSelectTab('chapters')
      return
    }
    if (stageKey === 'edit_raw') {
      navigate(`/projects/${projectId}?tab=chapters&edit=${chapter.id}`)
      return
    }
    if (stageKey === 'extract_shots') {
      navigate(getChapterShotsPath(projectId, chapter.id))
      return
    }
    if (stageKey === 'prepare_shots') {
      navigate(getChapterBoardPath(projectId, chapter.id))
      return
    }
    void ensureHasShotsBeforeShooting({
      projectId,
      chapterId: chapter.id,
      storyboardCount: chapter.storyboardCount,
      navigate,
    })
  }

  const handleRecommendedAction = () => {
    if (!recommendedChapter || !recommendedState) {
      onSelectTab('chapters')
      return
    }
    jumpToStage(recommendedState.key)
  }

  /** 四个阶段：数量 + 一句话说明 + 当前是否就是「下一步」所在阶段。 */
  const stages = [
    {
      key: 'edit_raw',
      label: '录入原文',
      hint: '还没有可拆分的章节原文',
      count: chaptersByIndex.filter((c) => getChapterPreparationState(c).key === 'edit_raw').length,
    },
    {
      key: 'extract_shots',
      label: '提取分镜',
      hint: '已有原文，等待拆成镜头',
      count: chaptersByIndex.filter((c) => getChapterPreparationState(c).key === 'extract_shots')
        .length,
    },
    {
      key: 'prepare_shots',
      label: '准备镜头',
      hint: '已有分镜，待补资产与对白',
      count: chaptersByIndex.filter((c) => getChapterPreparationState(c).key === 'prepare_shots')
        .length,
    },
    {
      key: 'shoot',
      label: '进入生成',
      hint: '镜头已就绪，可开始出片',
      count: chaptersByIndex.filter((c) => getChapterPreparationState(c).key === 'shoot').length,
    },
  ]

  const totalAssets = project.stats.roles + project.stats.scenes + project.stats.props

  return (
    <div className="space-y-5">
      {/* 1. 下一步：整个页面只有一个主动作 */}
      <Card size="small">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs text-muted-foreground">下一步</div>
            <div className="mt-1 text-lg font-medium">{recommendedActionLabel}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {recommendedChapter && recommendedState
                ? `第${recommendedChapter.index}章 · ${recommendedState.hint}`
                : '项目还没有章节，先建第一章再拆镜头'}
            </div>
          </div>

          {/* 只保留一个主动作：次要入口在顶部工具栏与下方「全部章节」里已有，重复放会分散注意力 */}
          <Button
            type="primary"
            icon={recommendedState?.primaryIcon ?? <VideoCameraOutlined />}
            onClick={handleRecommendedAction}
          >
            {recommendedActionLabel}
          </Button>
        </div>
      </Card>

      {/* 2. 流程走到哪：阶段是章节维度，镜头状态是镜头维度，两者分开但同屏 */}
      <Card
        size="small"
        title="流程进度"
        extra={
          <Button type="link" className="p-0" onClick={() => projectId && navigate(getProjectChaptersPath(projectId))}>
            全部章节
          </Button>
        }
      >
        {chapters.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-sm text-muted-foreground">
            <span>还没有任何章节</span>
            <Button type="primary" onClick={() => onSelectTab('chapters')}>
              创建第一章
            </Button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {stages.map((stage, index) => {
                const isNext = recommendedState?.key === stage.key
                return (
                  <button
                    key={stage.key}
                    type="button"
                    onClick={() => jumpToStage(stage.key)}
                    className={`rounded-lg border p-3 text-left transition-colors ${
                      isNext
                        ? 'border-primary bg-primary/10'
                        : 'border-gray-200 bg-card hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">
                        第 {index + 1} 步 · {stage.label}
                      </span>
                      {isNext ? (
                        <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] text-primary">
                          下一步
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-1 text-2xl font-semibold">{stage.count}</div>
                    <div className="mt-0.5 text-xs text-gray-500">{stage.hint}</div>
                  </button>
                )
              })}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-gray-100 pt-3 text-sm">
              <span className="text-gray-500">
                镜头总数 <span className="font-medium text-gray-900">{flowStats.totalShots}</span>
              </span>
              <span className="inline-flex items-center gap-1.5 text-gray-600">
                <span className="h-1.5 w-1.5 rounded-full bg-state-pending" />
                待确认 {flowStats.pendingConfirmShots}
              </span>
              <span className="inline-flex items-center gap-1.5 text-gray-600">
                <span className="h-1.5 w-1.5 rounded-full bg-state-ready" />
                已就绪 {flowStats.readyShots}
              </span>
              <span className="inline-flex items-center gap-1.5 text-gray-600">
                <span className="h-1.5 w-1.5 rounded-full bg-run-running" />
                生成中 {flowStats.generatingShots}
              </span>
              {flowStatsLoading ? <span className="text-xs text-gray-400">统计更新中…</span> : null}
            </div>
          </>
        )}
      </Card>

      {/* 3. 资产：只展示真实数量，不再用假进度条 */}
      <Card
        size="small"
        title="项目资产"
        extra={
          <Button type="link" className="p-0" onClick={() => navigate('/assets')}>
            管理资产
          </Button>
        }
      >
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: '角色', count: project.stats.roles, icon: <FileSearchOutlined /> },
            { label: '场景', count: project.stats.scenes, icon: <FileSearchOutlined /> },
            { label: '道具', count: project.stats.props, icon: <FileSearchOutlined /> },
          ].map((item) => (
            <div key={item.label} className="rounded-lg border border-gray-200 px-3 py-2">
              <div className="text-xs text-gray-500">{item.label}</div>
              <div className="mt-1 flex items-baseline gap-1">
                <span className="text-xl font-semibold">{item.count}</span>
                <span className="text-xs text-gray-500">项</span>
              </div>
            </div>
          ))}
        </div>
        {totalAssets === 0 ? (
          <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
            <ClockCircleOutlined />
            还没有资产，先在章节里提取分镜，系统会生成候选角色/场景/道具
          </div>
        ) : (
          <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
            <CheckCircleOutlined />
            资产已建立，镜头准备阶段会引用这些资产
          </div>
        )}
      </Card>
    </div>
  )
}
