/**
 * 章节级「一键准备」向导。
 *
 * 为什么存在：
 *   现有流程把「拆分镜 → 提取资产/对话 → 建资产关联 → 生成各类资产图」拆散在
 *   不同页面与按钮上（章节页、资产页 4 个 Tab、废弃的 ChapterPrep 等），
 *   用户需要大量点击与跳转才能推进一集。本组件把这几步串成一个向导，
 *   并在真正花代价（付费生成）之前给出一份检查清单。
 *
 * 流程（严格按用户诉求：先检查，再按类目顺序并发生成）：
 *   1. 检查：列出已有分镜数、各类资产与其提示词预览、参考图状态
 *   2. 用户确认后执行：
 *      - 无分镜 → 拆分镜
 *      - 无提取候选 → 提取资产/对话（script_division 传 {}，后端从库内分镜重建）
 *      - 未建资产 → 批量创建资产并建立镜头关联
 *      - 按 服装 → 场景 → 道具 → 角色 的顺序逐类批量生成（每类内部并发生成）
 *   3. 汇总每一阶段的结果（成功/跳过/失败）
 *
 * 顺序设计说明：角色定妆照会引用「演员图 + 服装图」，因此服装必须先行；
 * 场景/道具作为画面环境次之；角色最后，能拿到最完整的参考素材。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Descriptions,
  Empty,
  Modal,
  Progress,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  FilmService,
  ScriptProcessingService,
  StudioEntitiesService,
  StudioImageTasksService,
  StudioShotsService,
} from '../../../../services/generated'

const { Text, Paragraph } = Typography

/** 资产类型顺序：服装 → 场景 → 道具 → 角色（角色图依赖服装图）。 */
const ASSET_ORDER = ['costume', 'scene', 'prop', 'character'] as const
type AssetType = (typeof ASSET_ORDER)[number]

const ASSET_LABEL: Record<AssetType, string> = {
  costume: '服装',
  scene: '场景',
  prop: '道具',
  character: '角色',
}

interface AssetRow {
  id: string
  name: string
  description?: string
  thumbnail?: string
}

interface StageResult {
  key: string
  label: string
  status: 'pending' | 'running' | 'done' | 'skipped' | 'failed'
  detail?: string
}

export interface ChapterPrepareWizardProps {
  open: boolean
  projectId: string
  chapterId: string
  chapterIndex: number
  chapterTitle: string
  /** 章节现有分镜数（0 表示尚未拆分镜） */
  storyboardCount: number
  /** 章节原文，用于拆分镜 */
  rawText?: string | null
  onClose: () => void
  /** 任一步骤产生数据变更后调用，用于刷新列表 */
  onFinished?: () => void
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const ChapterPrepareWizard: React.FC<ChapterPrepareWizardProps> = ({
  open,
  projectId,
  chapterId,
  chapterIndex,
  chapterTitle,
  storyboardCount,
  rawText,
  onClose,
  onFinished,
}) => {
  const [phase, setPhase] = useState<'inspect' | 'running' | 'done'>('inspect')
  const [loadingAssets, setLoadingAssets] = useState(false)
  const [assets, setAssets] = useState<Record<AssetType, AssetRow[]>>({
    costume: [],
    scene: [],
    prop: [],
    character: [],
  })
  const [promptCache, setPromptCache] = useState<Record<string, string>>({})
  const [promptLoading, setPromptLoading] = useState<Record<string, boolean>>({})
  const [stages, setStages] = useState<StageResult[]>([])
  const [progress, setProgress] = useState(0)
  /** 已完成的阶段数，用于计算整体进度 */
  const finishedRef = useRef(0)

  const totalAssets = useMemo(
    () => ASSET_ORDER.reduce((sum, t) => sum + assets[t].length, 0),
    [assets],
  )

  /** 拉取项目内四类资产，用于检查清单与生成范围。 */
  const loadAssets = useCallback(async () => {
    setLoadingAssets(true)
    try {
      const result: Record<AssetType, AssetRow[]> = {
        costume: [],
        scene: [],
        prop: [],
        character: [],
      }
      // 逐类拉取：生成的 list 接口不提供 project_id 过滤，项目内资产规模小，直接取全量。
      for (const type of ASSET_ORDER) {
        try {
          const resp = await StudioEntitiesService.listEntitiesApiV1StudioEntitiesEntityTypeGet({
            entityType: type,
            page: 1,
            pageSize: 200,
          })
          const items = (resp.data as { items?: AssetRow[] } | undefined)?.items ?? []
          result[type] = items.map((it) => ({
            id: String(it.id),
            name: String(it.name ?? ''),
            description: it.description ?? '',
            thumbnail: it.thumbnail ?? '',
          }))
        } catch {
          result[type] = []
        }
      }
      setAssets(result)
    } finally {
      setLoadingAssets(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      setPhase('inspect')
      setStages([])
      setProgress(0)
      finishedRef.current = 0
      setPromptCache({})
      void loadAssets()
    }
  }, [open, loadAssets])

  /** 按需加载单个资产的最终提示词（避免一次性 N 次请求）。
   *
   * 注意 render-prompt 需要的是「资产图片行 ID」（costume_images.id 等），
   * 不是资产本身 ID。因此先查该资产的图片行，取第一张（front 优先）的 id。
   */
  const loadPrompt = useCallback(
    async (type: AssetType, assetId: string) => {
      const key = `${type}:${assetId}`
      if (promptCache[key] || promptLoading[key]) return
      setPromptLoading((prev) => ({ ...prev, [key]: true }))
      try {
        // 1) 取该资产的图片行（每个资产创建时至少有一个 front 槽位）
        const imagesResp = await StudioEntitiesService.listEntityImagesApiV1StudioEntitiesEntityTypeEntityIdImagesGet(
          { entityType: type, entityId: assetId },
        )
        const rawImages = imagesResp.data as
          | { items?: Array<{ id?: number; view_angle?: string }> }
          | Array<{ id?: number; view_angle?: string }>
          | undefined
        const imageList = Array.isArray(rawImages) ? rawImages : (rawImages?.items ?? [])
        if (!imageList.length) {
          setPromptCache((prev) => ({ ...prev, [key]: '该资产还没有图片槽位，无法渲染提示词' }))
          return
        }
        // front 视角优先，其次取第一条
        const front = imageList.find((i) => String(i.view_angle ?? '').toUpperCase() === 'FRONT')
        const imageId = Number((front ?? imageList[0]).id)
        if (!Number.isFinite(imageId)) {
          setPromptCache((prev) => ({ ...prev, [key]: '图片行 ID 非法，无法渲染提示词' }))
          return
        }

        // 2) 用 image_id 渲染最终提示词
        const resp =
          await StudioImageTasksService.renderAssetImagePromptApiV1StudioImageTasksAssetsAssetTypeAssetIdRenderPromptPost(
            {
              assetType: type,
              assetId,
              requestBody: { image_id: imageId, prompt: null, images: [] },
            },
          )
        const rendered = (resp.data as { prompt?: string } | undefined)?.prompt ?? ''
        setPromptCache((prev) => ({ ...prev, [key]: rendered || '（空提示词）' }))
      } catch (error) {
        setPromptCache((prev) => ({
          ...prev,
          [key]: `加载失败：${error instanceof Error ? error.message : String(error)}`,
        }))
      } finally {
        setPromptLoading((prev) => ({ ...prev, [key]: false }))
      }
    },
    [promptCache, promptLoading],
  )

  /** 轮询任务直到结束（用于拆分镜/提取这类异步任务）。 */
  const waitTask = useCallback(async (taskId: string, timeoutMs = 15 * 60 * 1000) => {
    const started = Date.now()
    while (Date.now() - started < timeoutMs) {
      try {
        const resp = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
        const status = String((resp.data as { status?: string } | undefined)?.status ?? '')
        if (status === 'succeeded') return
        if (status === 'failed' || status === 'cancelled') {
          const detail = (resp.data as { error?: string } | undefined)?.error
          throw new Error(detail || `任务状态 ${status}`)
        }
      } catch (error) {
        // 网络抖动不立即失败，继续轮询；只有明确业务失败才抛
        if (error instanceof Error && /任务状态/.test(error.message)) throw error
      }
      await sleep(2500)
    }
    throw new Error('任务超时（15 分钟）')
  }, [])

  const updateStage = useCallback((key: string, patch: Partial<StageResult>) => {
    setStages((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)))
  }, [])

  const bumpProgress = useCallback((total: number) => {
    finishedRef.current += 1
    setProgress(Math.round((finishedRef.current / total) * 100))
  }, [])

  /** 执行完整准备流程。 */
  const run = useCallback(async () => {
    const plan: StageResult[] = []
    if (storyboardCount === 0) plan.push({ key: 'divide', label: '拆分镜', status: 'pending' })
    plan.push({ key: 'extract', label: '提取资产与对白候选', status: 'pending' })
    plan.push({ key: 'create', label: '创建资产并建立镜头关联', status: 'pending' })
    for (const type of ASSET_ORDER) {
      if (assets[type].length > 0) {
        plan.push({ key: `img:${type}`, label: `生成${ASSET_LABEL[type]}图`, status: 'pending' })
      }
    }
    if (plan.length === 0) {
      message.info('当前章节没有可执行的准备工作')
      return
    }

    setStages(plan)
    setPhase('running')
    setProgress(0)
    finishedRef.current = 0
    const total = plan.length
    let failed = false

    try {
      // --- 1. 拆分镜 ---
      if (storyboardCount === 0) {
        const key = 'divide'
        updateStage(key, { status: 'running' })
        const text = (rawText ?? '').trim()
        if (!text) {
          updateStage(key, { status: 'failed', detail: '章节缺少原文，无法拆分镜' })
          failed = true
        } else {
          try {
            const resp =
              await ScriptProcessingService.divideScriptAsyncApiV1ScriptProcessingDivideAsyncPost({
                requestBody: { chapter_id: chapterId, script_text: text, write_to_db: true },
              })
            const taskId = String((resp.data as { task_id?: string })?.task_id ?? '')
            if (!taskId) throw new Error('未返回任务 ID')
            await waitTask(taskId)
            updateStage(key, { status: 'done', detail: '分镜已写入' })
          } catch (error) {
            updateStage(key, {
              status: 'failed',
              detail: error instanceof Error ? error.message : String(error),
            })
            failed = true
          }
        }
        bumpProgress(total)
        if (failed) throw new Error('拆分镜失败，流程中止')
      }

      // --- 2. 提取资产/对白候选 ---
      {
        const key = 'extract'
        updateStage(key, { status: 'running' })
        try {
          const resp =
            await ScriptProcessingService.extractScriptAsyncApiV1ScriptProcessingExtractAsyncPost({
              // script_division 传空对象：后端会从库内分镜重建（见 script_processing_worker）。
              requestBody: { project_id: projectId, chapter_id: chapterId, script_division: {} },
            })
          const taskId = String((resp.data as { task_id?: string })?.task_id ?? '')
          if (!taskId) throw new Error('未返回任务 ID')
          await waitTask(taskId)
          updateStage(key, { status: 'done', detail: '候选已生成' })
        } catch (error) {
          updateStage(key, {
            status: 'failed',
            detail: error instanceof Error ? error.message : String(error),
          })
          failed = true
        }
        bumpProgress(total)
        if (failed) throw new Error('提取失败，流程中止')
      }

      // --- 3. 创建资产并建立关联 ---
      {
        const key = 'create'
        updateStage(key, { status: 'running' })
        try {
          const resp =
            await StudioShotsService.batchCreateAssetsFromCandidatesApiV1StudioShotsExtractedCandidatesBatchCreateAssetsPost(
              { requestBody: { chapter_id: chapterId } },
            )
          const data = resp.data as
            | { created?: unknown[]; linked?: unknown[]; skipped?: unknown[] }
            | undefined
          const created = data?.created?.length ?? 0
          const linked = data?.linked?.length ?? 0
          const skipped = data?.skipped?.length ?? 0
          updateStage(key, {
            status: 'done',
            detail: `新建 ${created} / 关联 ${linked} / 跳过 ${skipped}`,
          })
          // 资产可能新增，重新拉一次供后续生成范围使用
          await loadAssets()
        } catch (error) {
          updateStage(key, {
            status: 'failed',
            detail: error instanceof Error ? error.message : String(error),
          })
          failed = true
        }
        bumpProgress(total)
        if (failed) throw new Error('创建资产失败，流程中止')
      }

      // --- 4. 按类目顺序生成资产图（每类内部并发生成）---
      //
      // 重要：只对「尚无参考图」的资产提交生成，避免对已出图的资产重复扣费。
      // 后端 batch-image-tasks 不检查 file_id 是否已有值（其语义是「一键全部重新生成」），
      // 因此这里用 asset_ids 显式限定范围；若某类资产已全部有图则直接跳过该阶段。
      for (const type of ASSET_ORDER) {
        const pending = assets[type].filter((a) => !a.thumbnail)
        if (assets[type].length === 0) continue
        const key = `img:${type}`
        if (pending.length === 0) {
          updateStage(key, { status: 'skipped', detail: `全部 ${assets[type].length} 个资产已有图` })
          bumpProgress(total)
          continue
        }
        updateStage(key, { status: 'running', detail: `待生成 ${pending.length} / 共 ${assets[type].length}` })
        try {
          const resp =
            await StudioImageTasksService.createBatchAssetImageTasksApiV1StudioImageTasksAssetsBatchImageTasksPost(
              {
                requestBody: {
                  project_id: projectId,
                  asset_type: type,
                  asset_ids: pending.map((a) => a.id),
                },
              },
            )
          const data = resp.data as
            | { tasks?: unknown[]; skipped?: unknown[]; enqueue_failed?: unknown[] }
            | undefined
          const ok = data?.tasks?.length ?? 0
          const skip = data?.skipped?.length ?? 0
          const fail = data?.enqueue_failed?.length ?? 0
          updateStage(key, {
            status: 'done',
            detail: `已提交 ${ok} / 跳过 ${skip} / 入队失败 ${fail}`,
          })
        } catch (error) {
          updateStage(key, {
            status: 'failed',
            detail: error instanceof Error ? error.message : String(error),
          })
        }
        bumpProgress(total)
      }

      setPhase('done')
      message.success('准备流程已执行完成，可在任务中心查看生成进度')
      onFinished?.()
    } catch (error) {
      setPhase('done')
      message.error(error instanceof Error ? error.message : '准备流程中断')
      onFinished?.()
    }
  }, [
    assets,
    bumpProgress,
    chapterId,
    loadAssets,
    onFinished,
    projectId,
    rawText,
    storyboardCount,
    updateStage,
    waitTask,
  ])

  const renderInspect = () => (
    <div className="space-y-4">
      <Descriptions size="small" column={3} bordered>
        <Descriptions.Item label="章节">{`第${chapterIndex}集 ${chapterTitle || ''}`}</Descriptions.Item>
        <Descriptions.Item label="分镜数">
          {storyboardCount > 0 ? storyboardCount : <Text type="warning">0（将先拆分镜）</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="资产总数">
          {loadingAssets ? <Spin size="small" /> : totalAssets}
        </Descriptions.Item>
      </Descriptions>

      {storyboardCount === 0 && !(rawText ?? '').trim() && (
        <Alert type="error" showIcon message="章节缺少原文，无法拆分镜" />
      )}

      <Alert
        type="info"
        showIcon
        message="生成顺序：服装 → 场景 → 道具 → 角色"
        description={
          <div>
            <div>角色定妆照会引用服装图，因此服装必须先生成；每类内部并发生成，避免互相等待。</div>
            <div className="mt-1">
              <Text strong>只会为「还没有参考图」的资产提交生成</Text>
              ，已有图的资产不会重复扣费；如需重新抽图，请到对应资产页手动重抽。
            </div>
          </div>
        }
      />

      <div>
        <Text strong>检查清单</Text>
        <Text type="secondary" className="ml-2">
          （展开可查看最终提示词；确认无误后再开始生成）
        </Text>
        <div className="mt-2">
          {loadingAssets ? (
            <div className="py-6 text-center">
              <Spin />
            </div>
          ) : totalAssets === 0 ? (
            <Empty description="当前项目还没有资产，将先执行提取与创建" />
          ) : (
            <Collapse
              size="small"
              items={ASSET_ORDER.filter((t) => assets[t].length > 0).map((type) => ({
                key: type,
                label: (
                  <Space>
                    <Tag color="blue">{ASSET_LABEL[type]}</Tag>
                    <Text>{assets[type].length} 个</Text>
                  </Space>
                ),
                children: (
                  <Table
                    size="small"
                    rowKey="id"
                    pagination={false}
                    dataSource={assets[type]}
                    columns={[
                      { title: '名称', dataIndex: 'name', width: 160 },
                      {
                        title: '描述',
                        dataIndex: 'description',
                        ellipsis: true,
                        render: (v: string) => v || <Text type="secondary">—</Text>,
                      },
                      {
                        title: '参考图',
                        dataIndex: 'thumbnail',
                        width: 120,
                        render: (v: string) =>
                          v ? (
                            <Tag color="green">已有</Tag>
                          ) : (
                            <Tag color="orange">待生成</Tag>
                          ),
                      },
                      {
                        title: '提示词',
                        key: 'prompt',
                        width: 110,
                        render: (_: unknown, row: AssetRow) => {
                          const key = `${type}:${row.id}`
                          const cached = promptCache[key]
                          return (
                            <Button
                              size="small"
                              type="link"
                              loading={promptLoading[key]}
                              onClick={() => void loadPrompt(type, row.id)}
                            >
                              {cached ? '重新加载' : '查看'}
                            </Button>
                          )
                        },
                      },
                    ]}
                    expandable={{
                      expandedRowRender: (row: AssetRow) => {
                        const key = `${type}:${row.id}`
                        const text = promptCache[key]
                        if (!text) return <Text type="secondary">点击「查看」加载提示词</Text>
                        return (
                          <Paragraph
                            style={{ marginBottom: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}
                            copyable={{ text }}
                          >
                            {text}
                          </Paragraph>
                        )
                      },
                      rowExpandable: (row: AssetRow) => Boolean(promptCache[`${type}:${row.id}`]),
                    }}
                  />
                ),
              }))}
            />
          )}
        </div>
      </div>
    </div>
  )

  const renderStages = () => (
    <div className="space-y-4">
      <Progress percent={progress} status={phase === 'done' ? 'success' : 'active'} />
      <Steps
        direction="vertical"
        size="small"
        current={stages.findIndex((s) => s.status === 'running') >= 0
          ? stages.findIndex((s) => s.status === 'running')
          : stages.length}
        items={stages.map((s) => ({
          title: s.label,
          status:
            s.status === 'done'
              ? 'finish'
              : s.status === 'failed'
                ? 'error'
                : s.status === 'running'
                  ? 'process'
                  : 'wait',
          description: s.detail,
        }))}
      />
    </div>
  )

  const footer = useMemo(() => {
    if (phase === 'inspect') {
      return [
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="run"
          type="primary"
          onClick={() => void run()}
          disabled={storyboardCount === 0 && !(rawText ?? '').trim()}
        >
          确认并开始准备
        </Button>,
      ]
    }
    if (phase === 'running') {
      return [
        <Button key="close" disabled>
          执行中…
        </Button>,
      ]
    }
    return [
      <Button key="close" type="primary" onClick={onClose}>
        完成
      </Button>,
    ]
  }, [onClose, phase, rawText, run, storyboardCount])

  return (
    <Modal
      open={open}
      title="一键准备本集"
      width={920}
      onCancel={phase === 'running' ? undefined : onClose}
      maskClosable={phase !== 'running'}
      closable={phase !== 'running'}
      footer={footer}
      destroyOnClose
    >
      {phase === 'inspect' ? renderInspect() : renderStages()}
    </Modal>
  )
}

export default ChapterPrepareWizard