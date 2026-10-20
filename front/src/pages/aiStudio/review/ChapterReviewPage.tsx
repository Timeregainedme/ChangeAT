/**
 * 章节检查页（P4）。
 *
 * 存在意义：
 *   分镜编辑页负责「提取与确认」，工作室负责「生成」，但在开工前还缺一个
 *   「按顺序把素材过一遍」的检查位。本页把检查内容固定成三段：
 *
 *     参考图  →  分镜  →  对话
 *
 *   每一段只做「看 + 就地改 + 必要的重抽」，并给出可量化的进度，
 *   让用户在进入工作室（花钱生成）之前有明确的自检闭环。
 *
 * 职责边界（与 AGENTS.md 的页面职责约定一致）：
 *   - 不承担提取候选的确认入口（候选仍回分镜编辑页处理），避免职责混淆；
 *   - 不承担成片生成与视频参数配置（那是工作室的职责）；
 *   - 修改范围限定在：资产参考图重抽、分镜五个生成字段、台词文案/情绪/配音。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Card, Segmented, Space, Spin, Tag, Typography, message } from 'antd'
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  MessageOutlined,
  PictureOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import {
  StudioChaptersService,
  StudioShotDetailsService,
  StudioShotsService,
} from '../../../services/generated'
import type {
  ChapterRead,
  ShotDetailRead,
  ShotPreparationStateRead,
  ShotRead,
} from '../../../services/generated'
import { getChapterShotEditPath, getChapterShotsPath, getChapterStudioPath } from '../project/ProjectWorkbench/routes'
import { ReviewAssetSection } from './components/ReviewAssetSection'
import { ReviewShotSection } from './components/ReviewShotSection'
import { ReviewDialogueSection } from './components/ReviewDialogueSection'
import type {
  ReviewAssetRow,
  ReviewAssetType,
  ReviewPendingCandidate,
  ShotBundle,
} from './types'

const { Text, Title } = Typography

type StageKey = 'assets' | 'shots' | 'dialogue'

const STAGE_ORDER: StageKey[] = ['assets', 'shots', 'dialogue']

const STAGE_META: Record<StageKey, { label: string; icon: React.ReactNode; hint: string }> = {
  assets: {
    label: '参考图',
    icon: <PictureOutlined />,
    hint: '确认本章用到的角色/服装/场景/道具都有参考图，缺图的先补图。',
  },
  shots: {
    label: '分镜',
    icon: <VideoCameraOutlined />,
    hint: '逐镜头核对时长、景别、角度、运镜与场景，这些都直接决定出片效果。',
  },
  dialogue: {
    label: '对话',
    icon: <MessageOutlined />,
    hint: '核对台词文案与情绪，并补齐配音（配音会作为视频参考音频）。',
  },
}

/** 简单并发控制：避免 20 个镜头一次性打满后端。 */
async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length)
  let cursor = 0
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor
      cursor += 1
      results[index] = await fn(items[index])
    }
  })
  await Promise.all(workers)
  return results
}

export function ChapterReviewPage() {
  const { projectId = '', chapterId = '' } = useParams<{ projectId: string; chapterId: string }>()
  const navigate = useNavigate()

  const [chapter, setChapter] = useState<ChapterRead | null>(null)
  const [bundles, setBundles] = useState<ShotBundle[]>([])
  const [loading, setLoading] = useState(true)
  const [stage, setStage] = useState<StageKey>('assets')

  /** 拉取章节 + 全部镜头 + 每镜头的分镜详情与准备状态。 */
  const load = useCallback(async () => {
    if (!projectId || !chapterId) return
    setLoading(true)
    try {
      const [chapterResp, shotsResp] = await Promise.all([
        StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId }),
        StudioShotsService.listShotsApiV1StudioShotsGet({
          chapterId,
          page: 1,
          pageSize: 100,
        }),
      ])
      const chapterData = (chapterResp.data ?? null) as ChapterRead | null
      const shotList = ((shotsResp.data as { items?: ShotRead[] } | undefined)?.items ?? []) as ShotRead[]
      shotList.sort((a, b) => a.index - b.index)
      setChapter(chapterData)

      const nextBundles = await mapLimit(shotList, 4, async (shot) => {
        // 分镜详情可能不存在（镜头刚提取、尚未保存基础信息），用 allSettled 容错。
        const [detailRes, prepRes] = await Promise.allSettled([
          StudioShotDetailsService.getShotDetailApiV1StudioShotDetailsShotIdGet({ shotId: shot.id }),
          StudioShotsService.getShotPreparationStateApiApiV1StudioShotsShotIdPreparationStateGet({
            shotId: shot.id,
          }),
        ])
        const detail =
          detailRes.status === 'fulfilled' ? ((detailRes.value.data ?? null) as ShotDetailRead | null) : null
        const prep =
          prepRes.status === 'fulfilled'
            ? ((prepRes.value.data ?? null) as ShotPreparationStateRead | null)
            : null
        return { shot, detail, prep } satisfies ShotBundle
      })
      setBundles(nextBundles)
    } catch (error) {
      message.error(error instanceof Error ? `加载检查数据失败：${error.message}` : '加载检查数据失败')
    } finally {
      setLoading(false)
    }
  }, [projectId, chapterId])

  useEffect(() => {
    void load()
  }, [load])

  /** 把各镜头资产总览聚合成「按实体去重」的清单 + 待确认候选。 */
  const { assets, pendingCandidates } = useMemo(() => {
    const assetMap = new Map<string, ReviewAssetRow>()
    const pending: ReviewPendingCandidate[] = []

    for (const bundle of bundles) {
      const shotLabel = `#${bundle.shot.index + 1}`
      const items = bundle.prep?.assets_overview?.items ?? []
      for (const item of items) {
        if (item.is_linked && item.linked_entity_id) {
          const key = `${item.type}:${item.linked_entity_id}`
          const existing = assetMap.get(key)
          if (existing) {
            if (!existing.shotLabels.includes(shotLabel)) existing.shotLabels.push(shotLabel)
            if (!existing.thumbnail && item.thumbnail) existing.thumbnail = item.thumbnail
          } else {
            assetMap.set(key, {
              key,
              type: item.type as ReviewAssetType,
              entityId: item.linked_entity_id,
              name: item.name,
              thumbnail: item.thumbnail ?? null,
              shotLabels: [shotLabel],
              firstShotId: bundle.shot.id,
            })
          }
        } else if (item.candidate_status === 'pending' && item.candidate_id != null) {
          pending.push({
            key: `${item.type}:${item.name}:${bundle.shot.id}:${item.candidate_id}`,
            type: item.type as ReviewAssetType,
            name: item.name,
            candidateId: item.candidate_id,
            shotId: bundle.shot.id,
            shotLabel,
            description: item.description ?? null,
          })
        }
      }
    }

    const rows = Array.from(assetMap.values()).sort((a, b) => {
      const order: ReviewAssetType[] = ['character', 'costume', 'scene', 'prop']
      const diff = order.indexOf(a.type) - order.indexOf(b.type)
      return diff !== 0 ? diff : a.name.localeCompare(b.name, 'zh-Hans-CN')
    })
    return { assets: rows, pendingCandidates: pending }
  }, [bundles])

  const progress = useMemo(() => {
    const assetsReady = assets.filter((row) => Boolean(row.thumbnail)).length
    const shotsReady = bundles.filter(
      (bundle) =>
        bundle.detail &&
        (bundle.detail.duration ?? 0) > 0 &&
        bundle.detail.camera_shot &&
        bundle.detail.angle &&
        bundle.detail.movement,
    ).length
    const allLines = bundles.flatMap((bundle) => bundle.prep?.saved_dialogue_lines ?? [])
    const linesAudio = allLines.filter((line) => line.generated_audio_file_id).length
    return {
      assetsTotal: assets.length,
      assetsReady,
      shotsTotal: bundles.length,
      shotsReady,
      linesTotal: allLines.length,
      linesAudio,
      pendingCandidates: pendingCandidates.length,
    }
  }, [assets, bundles, pendingCandidates])

  /** 场景下拉选项：来自第一段聚合出的场景资产。 */
  const sceneOptions = useMemo(
    () =>
      assets
        .filter((row) => row.type === 'scene')
        .map((row) => ({ value: row.entityId, label: row.name })),
    [assets],
  )

  const openShot = (shotId: string) => {
    if (!projectId || !chapterId) return
    navigate(getChapterShotEditPath(projectId, chapterId, shotId))
  }

  const openAsset = (type: ReviewAssetType, entityId: string) => {
    if (type === 'character') {
      navigate(`/projects/${projectId}?tab=roles`)
      return
    }
    const tab = type === 'costume' ? 'costume' : type
    navigate(`/assets?tab=${tab}#${entityId}`)
  }

  const stageIndex = STAGE_ORDER.indexOf(stage)
  const stagePrev = stageIndex > 0 ? STAGE_ORDER[stageIndex - 1] : null
  const stageNext = stageIndex < STAGE_ORDER.length - 1 ? STAGE_ORDER[stageIndex + 1] : null

  const updateDetail = (shotId: string, detail: ShotDetailRead) => {
    setBundles((prev) =>
      prev.map((bundle) => (bundle.shot.id === shotId ? { ...bundle, detail } : bundle)),
    )
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spin tip="加载检查数据…" />
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto" style={{ flex: 1, minHeight: 0 }}>
      <div className="space-y-4 p-4" style={{ maxWidth: 1400, margin: '0 auto' }}>
        <Card size="small">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <Title level={5} className="!mb-1">
                检查流程 · {chapter ? `第 ${chapter.index + 1} 章 ${chapter.title}` : '章节'}
              </Title>
              <Text type="secondary" className="text-xs">
                按「参考图 → 分镜 → 对话」顺序自查一遍，再进入工作室生成，能显著减少返工与重复扣费。
              </Text>
            </div>
            <Space wrap>
              <Button icon={<ReloadOutlined />} onClick={() => void load()}>
                刷新
              </Button>
              <Button
                onClick={() => navigate(getChapterShotsPath(projectId, chapterId))}
              >
                分镜列表
              </Button>
              <Button
                type="primary"
                onClick={() => navigate(getChapterStudioPath(projectId, chapterId))}
              >
                进入工作室
              </Button>
            </Space>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
            <ProgressCard
              title="① 参考图"
              current={progress.assetsReady}
              total={progress.assetsTotal}
              detail={
                progress.pendingCandidates > 0
                  ? `另有 ${progress.pendingCandidates} 条候选待确认`
                  : '候选已处理完'
              }
              warn={progress.pendingCandidates > 0}
            />
            <ProgressCard
              title="② 分镜"
              current={progress.shotsReady}
              total={progress.shotsTotal}
              detail="字段完整（时长/景别/角度/运镜）"
            />
            <ProgressCard
              title="③ 对话"
              current={progress.linesAudio}
              total={progress.linesTotal}
              detail="已配音条数"
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <Segmented
              value={stage}
              onChange={(val) => setStage(val as StageKey)}
              options={STAGE_ORDER.map((key) => ({
                value: key,
                label: (
                  <span className="inline-flex items-center gap-1">
                    {STAGE_META[key].icon}
                    {STAGE_META[key].label}
                  </span>
                ),
              }))}
            />
            <Space>
              <Button
                icon={<ArrowLeftOutlined />}
                disabled={!stagePrev}
                onClick={() => stagePrev && setStage(stagePrev)}
              >
                上一段
              </Button>
              <Button
                type="default"
                disabled={!stageNext}
                onClick={() => stageNext && setStage(stageNext)}
              >
                下一段 <ArrowRightOutlined />
              </Button>
            </Space>
          </div>
        </Card>

        <Alert type="info" showIcon message={STAGE_META[stage].hint} />

        {bundles.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="本章还没有分镜"
            description={
              <Space>
                <span>请先在分镜编辑页完成「提取分镜」，再回来做检查。</span>
                <Button size="small" onClick={() => navigate(getChapterShotsPath(projectId, chapterId))}>
                  去分镜列表
                </Button>
              </Space>
            }
          />
        ) : (
          <>
            {stage === 'assets' ? (
              <ReviewAssetSection
                projectId={projectId}
                assets={assets}
                pendingCandidates={pendingCandidates}
                onChanged={() => void load()}
                onOpenAsset={openAsset}
                onOpenShot={openShot}
              />
            ) : null}

            {stage === 'shots' ? (
              <ReviewShotSection
                bundles={bundles}
                sceneOptions={sceneOptions}
                onUpdated={updateDetail}
                onOpenShot={openShot}
              />
            ) : null}

            {stage === 'dialogue' ? (
              <ReviewDialogueSection
                bundles={bundles}
                onChanged={() => void load()}
                onOpenShot={openShot}
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  )
}

/** 进度卡片：当前值/总数 + 一行说明，超期未达成时用橙色提醒。 */
function ProgressCard({
  title,
  current,
  total,
  detail,
  warn = false,
}: {
  title: string
  current: number
  total: number
  detail: string
  warn?: boolean
}) {
  const done = total > 0 && current >= total
  return (
    <div className="border rounded-md p-3 bg-gray-50">
      <div className="flex items-center justify-between">
        <Text strong>{title}</Text>
        <Tag color={done ? 'green' : warn ? 'red' : 'orange'}>
          {current} / {total}
        </Tag>
      </div>
      <div className="text-xs text-gray-500 mt-1">{detail}</div>
    </div>
  )
}

export default ChapterReviewPage
