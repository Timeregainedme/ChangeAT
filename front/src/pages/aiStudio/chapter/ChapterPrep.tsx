import type React from 'react'
import { useEffect, useMemo, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Collapse,
  Divider,
  Empty,
  Checkbox,
  Input,
  Layout,
  List,
  Modal,
  Skeleton,
  Space,
  Steps,
  Switch,
  Table,
  Tag,
  Tabs,
  Tooltip,
  message,
} from 'antd'
import type { TableColumnsType } from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  MergeCellsOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  FilmService,
  ScriptProcessingService,
  StudioChaptersService,
  StudioImageTasksService,
  StudioShotsService,
} from '../../../services/generated'
import type { ChapterRead, ScriptExtractRequest, ScriptDividerRequest } from '../../../services/generated'
import type { Chapter } from '../../../mocks/data'
import { ChapterRawTextEditorModal } from './components/ChapterRawTextEditorModal'

const { Header, Content } = Layout

type ExtractKind = 'storyboards' | 'roles' | 'scenes' | 'props'

type StoryboardSuggestion = {
  id: string
  index: number
  title: string
  preview: string
  paragraphRange: string
  duration: string
  actions: string[]
  roles: string[]
  scenes: string[]
  props: string[]
  isTransition?: boolean
}

type RoleItem = {
  id: string
  name: string
  aliases: string[]
  firstSeen: string
  description: string
  primary: boolean
}

type SceneItem = {
  id: string
  name: string
  indoorOutdoor: '室内' | '室外' | '未知'
  time: '白天' | '夜晚' | '未知'
  keywords: string[]
}

type PropItem = {
  id: string
  name: string
  owner?: string
  count: number
  key: boolean
}

type SceneDraft = SceneItem & { description?: string; imageUrl?: string }
type PropDraft = PropItem & { description?: string; imageUrl?: string }
type RoleDraft = RoleItem & { imageUrl?: string }

type StoryboardDraft = StoryboardSuggestion

type ExtractResults = {
  storyboards: StoryboardSuggestion[]
  roles: RoleItem[]
  scenes: SceneItem[]
  props: PropItem[]
}

// TODO: 后续可移除本页面的 Mock 辅助交互（实体编辑/从资产库选取等），核心提取与生成已接真实接口。

// 轮询异步任务直至终态（succeeded/failed/cancelled），返回最终 TaskStatusRead。
async function pollTaskUntilDone(taskId: string, onProgress?: (p: number) => void): Promise<string> {
  for (let i = 0; i < 120; i += 1) {
    const res = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
    const data = res.data ?? null
    const status = data?.status ?? 'pending'
    onProgress?.(data?.progress ?? 0)
    if (status === 'succeeded' || status === 'failed' || status === 'cancelled') {
      if (status !== 'succeeded') {
        throw new Error(`任务未成功：${status}`)
      }
      return status
    }
    await new Promise((r) => setTimeout(r, 1200))
  }
  throw new Error('任务轮询超时')
}

// 剧本 -> 分镜（divide-async）-> 项目级提取（extract-async）真实链路。
// 提取完成后，后端会把候选写入各镜头的 extracted_candidates，前端再聚合展示。
async function fetchPrepExtract(opts: {
  projectId: string
  chapterId: string
  scriptText: string
  onProgress?: (label: string, p: number) => void
}): Promise<ExtractResults> {
  const { projectId, chapterId, scriptText, onProgress } = opts

  onProgress?.('分镜切分', 0)
  const divided = await ScriptProcessingService.divideScriptAsyncApiV1ScriptProcessingDivideAsyncPost({
    requestBody: {
      script_text: scriptText,
      write_to_db: true,
      chapter_id: chapterId,
    } as ScriptDividerRequest,
  })
  const divideTaskId = divided.data?.task_id
  if (!divideTaskId) {
    throw new Error('divide-async 未返回 task_id')
  }
  await pollTaskUntilDone(divideTaskId, (p) => onProgress?.('分镜切分', p))

  onProgress?.('智能提取', 0)
  const extracted = await ScriptProcessingService.extractScriptAsyncApiV1ScriptProcessingExtractAsyncPost({
    requestBody: {
      project_id: projectId,
      chapter_id: chapterId,
      script_division: {}, // 服务端从库内分镜重建；保持接口契约
    } as ScriptExtractRequest,
  })
  const extractTaskId = extracted.data?.task_id
  if (!extractTaskId) {
    throw new Error('extract-async 未返回 task_id')
  }
  await pollTaskUntilDone(extractTaskId, (p) => onProgress?.('智能提取', p))

  return await collectExtractionResults(chapterId)
}

// 聚合章节下各镜头的提取候选 + 分镜，映射为页面 ExtractResults 结构。
async function collectExtractionResults(chapterId: string): Promise<ExtractResults> {
  const shotsRes = await StudioShotsService.listShotsApiV1StudioShotsGet({
    chapterId,
    page: 1,
    pageSize: 500,
  })
  const shotRows = shotsRes.data?.items ?? []

  const storyboards: StoryboardSuggestion[] = shotRows.map((s, i) => ({
    id: s.id ?? `shot-${i}`,
    index: s.index ?? i + 1,
    title: s.title ?? '',
    preview: (s.script_excerpt ?? '').slice(0, 60),
    paragraphRange: '',
    duration: '',
    actions: [],
    roles: [],
    scenes: [],
    props: [],
  }))

  const roles: RoleItem[] = []
  const scenes: SceneItem[] = []
  const props: PropItem[] = []
  const seen = { role: new Set<string>(), scene: new Set<string>(), prop: new Set<string>() }

  for (const shot of shotRows) {
    const shotId = shot.id
    if (!shotId) continue
    const candRes = await StudioShotsService.getShotExtractedCandidatesApiV1StudioShotsShotIdExtractedCandidatesGet({
      shotId,
    })
    for (const c of candRes.data ?? []) {
      const type = c.candidate_type
      const name = c.candidate_name
      const description = c.payload?.description ?? ''
      if (type === 'character' && !seen.role.has(name)) {
        seen.role.add(name)
        roles.push({ id: `role-${roles.length + 1}`, name, aliases: [], firstSeen: '', description, primary: true })
      } else if (type === 'scene' && !seen.scene.has(name)) {
        seen.scene.add(name)
        scenes.push({
          id: `scene-${scenes.length + 1}`,
          name,
          indoorOutdoor: '未知',
          time: '未知',
          keywords: [],
        })
      } else if (type === 'prop' && !seen.prop.has(name)) {
        seen.prop.add(name)
        props.push({ id: `prop-${props.length + 1}`, name, owner: undefined, count: 1, key: false })
      }
    }
  }

  return { storyboards, roles, scenes, props }
}

type EntityKind = 'roles' | 'scenes' | 'props'

type ExistingEntities = {
  roles: string[]
  scenes: string[]
  props: string[]
}

function entitiesStorageKey(projectId: string) {
  return `jellyfish_project_entities_v1:${projectId}`
}

function toUIChapter(c: ChapterRead): Chapter {
  return {
    id: c.id,
    projectId: c.project_id,
    index: c.index,
    title: c.title,
    summary: c.summary ?? '',
    storyboardCount: c.storyboard_count ?? 0,
    status: c.status ?? 'draft',
    updatedAt: new Date().toISOString(),
  }
}

const ChapterPrep: React.FC = () => {
  const { projectId, chapterId } = useParams<{ projectId?: string; chapterId?: string }>()
  const navigate = useNavigate()

  const [activeStep, setActiveStep] = useState(0)

  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [titleEditing, setTitleEditing] = useState(false)
  const [titleValue, setTitleValue] = useState('')

  const [rawText, setRawText] = useState('')
  const [, setCondensedText] = useState('')

  const [editorModalOpen, setEditorModalOpen] = useState(false)

  const [extracting, setExtracting] = useState(false)
  const [creatingAssets, setCreatingAssets] = useState(false)
  const [generatingImages, setGeneratingImages] = useState(false)
  const [lastImageTasks, setLastImageTasks] = useState<Array<{ asset_id?: string; task_id?: string; prompt?: string }>>([])
  const [results, setResults] = useState<ExtractResults>({ storyboards: [], roles: [], scenes: [], props: [] })
  const [extractReviewOpen, setExtractReviewOpen] = useState(false)
  const [extractReviewTab, setExtractReviewTab] = useState<EntityKind>('roles')
  const [existingEntities, setExistingEntities] = useState<ExistingEntities>({ roles: [], scenes: [], props: [] })
  const [selectedEntityKeys, setSelectedEntityKeys] = useState<Record<EntityKind, string[]>>({
    roles: [],
    scenes: [],
    props: [],
  })

  const [selectedKind, setSelectedKind] = useState<ExtractKind>('storyboards')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [sceneDrafts, setSceneDrafts] = useState<SceneDraft[]>([])
  const [propDrafts, setPropDrafts] = useState<PropDraft[]>([])
  const [roleDrafts, setRoleDrafts] = useState<RoleDraft[]>([])
  const [storyboardDrafts, setStoryboardDrafts] = useState<StoryboardDraft[]>([])

  const [selectedSceneIds, setSelectedSceneIds] = useState<string[]>([])
  const [selectedPropIds, setSelectedPropIds] = useState<string[]>([])
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])

  const [editEntityOpen, setEditEntityOpen] = useState(false)
  const [editEntityKind, setEditEntityKind] = useState<'scene' | 'prop' | 'role'>('scene')
  const [editEntityId, setEditEntityId] = useState<string | null>(null)
  const [editEntityName, setEditEntityName] = useState('')
  const [editEntityDesc, setEditEntityDesc] = useState('')

  const [addEntityOpen, setAddEntityOpen] = useState(false)
  const [addEntityKind, setAddEntityKind] = useState<'scene' | 'prop' | 'role'>('scene')
  const [addEntityName, setAddEntityName] = useState('')
  const [addEntityDesc, setAddEntityDesc] = useState('')

  const [pickFromAssetsOpen, setPickFromAssetsOpen] = useState(false)
  const [pickFromAssetsKind, setPickFromAssetsKind] = useState<'scene' | 'prop' | 'role'>('scene')
  const [pickFromAssetsSelected, setPickFromAssetsSelected] = useState<string[]>([])

  const [editStoryboardOpen, setEditStoryboardOpen] = useState(false)
  const [editingStoryboard, setEditingStoryboard] = useState<StoryboardDraft | null>(null)

  const handleFinishPrep = () => {
    if (!projectId) {
      navigate('/projects')
      return
    }
    navigate(`/projects/${projectId}?tab=chapters`)
  }

  // 预留：后续在 step 编辑区可展示字数/段落数

  useEffect(() => {
    if (!chapterId) return
    StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId })
      .then((res) => {
        const data = res.data
        if (!data) {
          setChapter(null)
          return
        }
        const ui = toUIChapter(data)
        setChapter(ui)
        setTitleValue(ui.title)

        const nextRaw = data.raw_text ?? ''
        const nextCondensed = data.condensed_text ?? ''
        setRawText(nextRaw)
        setCondensedText(nextCondensed)
        // 进入页面时若已有分镜/候选，直接聚合展示，避免整页空白。
        if (data.project_id) {
          void collectExtractionResults(chapterId)
            .then(setResults)
            .catch(() => undefined)
        }
      })
      .catch(() => {
        setChapter(null)
      })
  }, [chapterId])

  useEffect(() => {
    // 将提取结果映射为各 step 的可编辑草稿（尽量保留用户编辑/生成状态）
    setSceneDrafts((prev) => {
      const prevMap = new Map(prev.map((x) => [x.id, x]))
      return results.scenes.map((s) => ({ ...s, ...(prevMap.get(s.id) ?? {}) }))
    })
    setPropDrafts((prev) => {
      const prevMap = new Map(prev.map((x) => [x.id, x]))
      return results.props.map((p) => ({ ...p, ...(prevMap.get(p.id) ?? {}) }))
    })
    setRoleDrafts((prev) => {
      const prevMap = new Map(prev.map((x) => [x.id, x]))
      return results.roles.map((r) => ({ ...r, ...(prevMap.get(r.id) ?? {}) }))
    })
    setStoryboardDrafts((prev) => {
      const prevMap = new Map(prev.map((x) => [x.id, x]))
      return results.storyboards.map((sb) => ({ ...sb, ...(prevMap.get(sb.id) ?? {}) }))
    })
  }, [results.scenes, results.props, results.roles, results.storyboards])

  useEffect(() => {
    if (!projectId) return
    try {
      const raw = window.localStorage.getItem(entitiesStorageKey(projectId))
      const parsed = raw ? (JSON.parse(raw) as ExistingEntities) : null
      if (parsed && typeof parsed === 'object') {
        setExistingEntities({
          roles: Array.isArray(parsed.roles) ? parsed.roles : [],
          scenes: Array.isArray(parsed.scenes) ? parsed.scenes : [],
          props: Array.isArray(parsed.props) ? parsed.props : [],
        })
      }
    } catch {
      // ignore
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    try {
      window.localStorage.setItem(entitiesStorageKey(projectId), JSON.stringify(existingEntities))
    } catch {
      // ignore
    }
  }, [projectId, existingEntities])

  // 真实提取链路：divide-async -> extract-async -> 聚合候选/分镜展示。
  const runExtract = async (kind: 'all' | ExtractKind) => {
    if (!rawText.trim()) {
      message.warning('请先粘贴或输入原文')
      return
    }
    if (!projectId || !chapterId) {
      message.warning('缺少项目或章节上下文')
      return
    }
    setExtracting(true)
    try {
      const next = await fetchPrepExtract({
        projectId,
        chapterId,
        scriptText: rawText,
        onProgress: (_label, _p) => undefined,
      })
      setResults((prev) => {
        if (kind === 'all') return next
        switch (kind) {
          case 'storyboards':
            return { ...prev, storyboards: next.storyboards }
          case 'roles':
            return { ...prev, roles: next.roles }
          case 'scenes':
            return { ...prev, scenes: next.scenes }
          case 'props':
            return { ...prev, props: next.props }
          default:
            return prev
        }
      })
      message.success(`提取完成：分镜 ${next.storyboards.length} / 角色 ${next.roles.length} / 场景 ${next.scenes.length} / 道具 ${next.props.length}`)

      // 打开提取回显浮窗
      if (kind === 'roles' || kind === 'scenes' || kind === 'props') {
        setExtractReviewTab(kind)
      } else {
        setExtractReviewTab('roles')
      }
      setSelectedEntityKeys({ roles: [], scenes: [], props: [] })
      setExtractReviewOpen(true)
    } catch (err) {
      message.error(`提取失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setExtracting(false)
    }
  }

  // 一键从提取候选创建/关联资产（人物/场景/道具/服装落库）。
  const batchCreateAssets = async () => {
    if (!chapterId) {
      message.warning('缺少章节上下文')
      return
    }
    setCreatingAssets(true)
    try {
      const res = await StudioShotsService.batchCreateAssetsFromCandidatesApiV1StudioShotsExtractedCandidatesBatchCreateAssetsPost(
        {
          requestBody: { chapter_id: chapterId, types: undefined },
        },
      )
      const data = (res.data ?? {}) as Record<string, unknown>
      const created = data.created ?? []
      const linked = data.linked ?? []
      const skipped = data.skipped ?? []
      message.success(`资产就绪：新建 ${created.length} / 关联 ${linked.length} / 跳过 ${skipped.length}`)
      // 刷新候选展示（新资产已关联，重新聚合以保持最新状态）
      const next = await collectExtractionResults(chapterId)
      setResults(next)
    } catch (err) {
      message.error(`创建资产失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setCreatingAssets(false)
    }
  }

  // 一键批量生成资产参考图（人物/场景/道具/服装），任务提交后由工作室/资产页出图与抽卡。
  const batchGenerateAssetImages = async (assetType: 'character' | 'scene' | 'prop' | 'costume') => {
    setGeneratingImages(true)
    try {
      const res = await StudioImageTasksService.createBatchAssetImageTasksApiV1StudioImageTasksAssetsBatchImageTasksPost({
        requestBody: { asset_type: assetType, asset_ids: undefined },
      })
      const body = (res.data ?? {}) as Record<string, unknown>
      const tasks = Array.isArray(body.tasks) ? (body.tasks as Array<Record<string, unknown>>) : []
      const skipped = Array.isArray(body.skipped) ? body.skipped : []
      const typeLabel = { character: '角色', scene: '场景', prop: '道具', costume: '服装' }[assetType]
      message.success(
        skipped.length > 0
          ? `${typeLabel}参考图：已提交 ${tasks.length} 个任务，跳过 ${skipped.length}（无图片槽位）`
          : `${typeLabel}参考图：已提交 ${tasks.length} 个生成任务`,
      )
      setLastImageTasks(tasks)
    } catch (err) {
      message.error(`批量生成参考图失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setGeneratingImages(false)
    }
  }

  const existingSet = useMemo(() => {
    return {
      roles: new Set(existingEntities.roles),
      scenes: new Set(existingEntities.scenes),
      props: new Set(existingEntities.props),
    }
  }, [existingEntities])

  const addSelectedEntities = (kind: EntityKind) => {
    const selected = selectedEntityKeys[kind]
    if (selected.length === 0) {
      message.info('请先选择要添加的内容')
      return
    }
    const duplicates = selected.filter((name) => existingSet[kind].has(name))
    const uniques = selected.filter((name) => !existingSet[kind].has(name))

    const doAdd = () => {
      if (uniques.length === 0) {
        message.info('所选内容均已存在，无需添加')
        return
      }
      setExistingEntities((prev) => ({
        ...prev,
        [kind]: Array.from(new Set([...(prev[kind] as string[]), ...uniques])),
      }))
      setSelectedEntityKeys((prev) => ({ ...prev, [kind]: [] }))
      message.success(`已添加 ${uniques.length} 项`)
    }

    if (duplicates.length > 0) {
      Modal.confirm({
        title: '存在重复内容',
        content: `你选择的内容中有 ${duplicates.length} 项已存在，将自动跳过重复项，是否继续添加其余内容？`,
        okText: '继续添加',
        cancelText: '取消',
        onOk: doAdd,
      })
      return
    }
    doAdd()
  }

  const toggleSelectAllNew = (kind: EntityKind) => {
    const items =
      kind === 'roles'
        ? results.roles.map((r) => r.name)
        : kind === 'scenes'
          ? results.scenes.map((s) => s.name)
          : results.props.map((p) => p.name)
    const newOnes = items.filter((name) => !existingSet[kind].has(name))
    setSelectedEntityKeys((prev) => ({ ...prev, [kind]: newOnes }))
  }

  const openEditEntity = (kind: 'scene' | 'prop' | 'role', id: string) => {
    setEditEntityKind(kind)
    setEditEntityId(id)
    if (kind === 'scene') {
      const it = sceneDrafts.find((x) => x.id === id)
      setEditEntityName(it?.name ?? '')
      setEditEntityDesc(it?.description ?? '')
    } else if (kind === 'prop') {
      const it = propDrafts.find((x) => x.id === id)
      setEditEntityName(it?.name ?? '')
      setEditEntityDesc(it?.description ?? '')
    } else {
      const it = roleDrafts.find((x) => x.id === id)
      setEditEntityName(it?.name ?? '')
      setEditEntityDesc(it?.description ?? it?.description ?? '')
    }
    setEditEntityOpen(true)
  }

  const saveEditEntity = () => {
    if (!editEntityId) return
    if (editEntityKind === 'scene') {
      setSceneDrafts((prev) =>
        prev.map((x) => (x.id === editEntityId ? { ...x, name: editEntityName, description: editEntityDesc } : x)),
      )
    } else if (editEntityKind === 'prop') {
      setPropDrafts((prev) =>
        prev.map((x) => (x.id === editEntityId ? { ...x, name: editEntityName, description: editEntityDesc } : x)),
      )
    } else {
      setRoleDrafts((prev) =>
        prev.map((x) => (x.id === editEntityId ? { ...x, name: editEntityName, description: editEntityDesc } : x)),
      )
    }
    setEditEntityOpen(false)
    setEditEntityId(null)
    message.success('已保存（Mock）')
  }

  const openAddEntity = (kind: 'scene' | 'prop' | 'role') => {
    setAddEntityKind(kind)
    setAddEntityName('')
    setAddEntityDesc('')
    setAddEntityOpen(true)
  }

  const addEntity = () => {
    if (!addEntityName.trim()) {
      message.warning('请输入名称')
      return
    }
    const id = `${addEntityKind}-${Date.now()}`
    if (addEntityKind === 'scene') {
      setSceneDrafts((prev) => [
        ...prev,
        {
          id,
          name: addEntityName.trim(),
          indoorOutdoor: '未知' as const,
          time: '未知' as const,
          keywords: [] as string[],
          description: addEntityDesc,
        },
      ])
    } else if (addEntityKind === 'prop') {
      setPropDrafts((prev) => [
        ...prev,
        { id, name: addEntityName.trim(), count: 1, key: false, description: addEntityDesc },
      ])
    } else {
      setRoleDrafts((prev) => [
        ...prev,
        {
          id,
          name: addEntityName.trim(),
          aliases: [],
          firstSeen: '',
          description: addEntityDesc,
          primary: true,
        },
      ])
    }
    setAddEntityOpen(false)
    message.success('已添加（Mock）')
  }

  const openPickFromAssets = (kind: 'scene' | 'prop' | 'role') => {
    setPickFromAssetsKind(kind)
    setPickFromAssetsSelected([])
    setPickFromAssetsOpen(true)
  }

  const confirmPickFromAssets = () => {
    if (pickFromAssetsSelected.length === 0) {
      message.info('请先选择要添加的内容')
      return
    }
    if (pickFromAssetsKind === 'scene') {
      setSceneDrafts((prev) => [
        ...prev,
        ...pickFromAssetsSelected.map((name) => ({
          id: `asset-scene-${name}`,
          name,
          indoorOutdoor: '未知' as const,
          time: '未知' as const,
          keywords: [] as string[],
          description: '来自资产库（Mock）',
        })),
      ])
    } else if (pickFromAssetsKind === 'prop') {
      setPropDrafts((prev) => [
        ...prev,
        ...pickFromAssetsSelected.map((name) => ({
          id: `asset-prop-${name}`,
          name,
          count: 1,
          key: false,
          description: '来自资产库（Mock）',
        })),
      ])
    } else {
      setRoleDrafts((prev) => [
        ...prev,
        ...pickFromAssetsSelected.map((name) => ({
          id: `asset-role-${name}`,
          name,
          aliases: [],
          firstSeen: '',
          description: '来自资产库（Mock）',
          primary: true,
        })),
      ])
    }
    setPickFromAssetsOpen(false)
    message.success('已从资产库添加（Mock）')
  }

  const generateImages = (kind: 'scene' | 'prop' | 'role') => {
    const stamp = Date.now()
    const url = `mock://generated/${kind}/${stamp}`
    if (kind === 'scene') {
      setSceneDrafts((prev) =>
        prev.map((x) => (selectedSceneIds.includes(x.id) ? { ...x, imageUrl: url } : x)),
      )
      message.success('已生成场景图片（Mock）')
      return
    }
    if (kind === 'prop') {
      setPropDrafts((prev) =>
        prev.map((x) => (selectedPropIds.includes(x.id) ? { ...x, imageUrl: url } : x)),
      )
      message.success('已生成道具图片（Mock）')
      return
    }
    setRoleDrafts((prev) =>
      prev.map((x) => (selectedRoleIds.includes(x.id) ? { ...x, imageUrl: url } : x)),
    )
    message.success('已生成角色图片（Mock）')
  }

  const openEditStoryboard = (sb: StoryboardDraft) => {
    setEditingStoryboard(sb)
    setEditStoryboardOpen(true)
  }

  const saveStoryboard = () => {
    if (!editingStoryboard) return
    setStoryboardDrafts((prev) => prev.map((x) => (x.id === editingStoryboard.id ? editingStoryboard : x)))
    setEditStoryboardOpen(false)
    setEditingStoryboard(null)
    message.success('已保存分镜（Mock）')
  }

  const currentItemsCount = useMemo(() => {
    return {
      storyboards: results.storyboards.length,
      roles: results.roles.length,
      scenes: results.scenes.length,
      props: results.props.length,
    }
  }, [results])

  const selectedStoryboard = useMemo(
    () => results.storyboards.find((x) => x.id === selectedId) ?? null,
    [results.storyboards, selectedId],
  )

  const selectedRole = useMemo(
    () => results.roles.find((x) => x.id === selectedId) ?? null,
    [results.roles, selectedId],
  )

  const selectedScene = useMemo(
    () => results.scenes.find((x) => x.id === selectedId) ?? null,
    [results.scenes, selectedId],
  )

  const selectedProp = useMemo(
    () => results.props.find((x) => x.id === selectedId) ?? null,
    [results.props, selectedId],
  )

  return (
    <Layout style={{ height: '100%', minHeight: 0, background: '#eef2f7' }}>
      <Header
        style={{
          padding: '0 16px',
          background: '#fff',
          borderBottom: '1px solid #e2e8f0',
          boxShadow: '0 2px 4px rgba(0,0,0,0.04)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <Link
          to={projectId ? `/projects/${projectId}?tab=chapters` : '/projects'}
          className="text-gray-600 hover:text-blue-600 flex items-center gap-1"
        >
          <ArrowLeftOutlined /> 返回章节列表
        </Link>
        <Divider type="vertical" />

        <div className="min-w-0 flex-1 flex items-center gap-2">
          {titleEditing ? (
            <Input
              value={titleValue}
              autoFocus
              onChange={(e) => setTitleValue(e.target.value)}
              onBlur={() => setTitleEditing(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setTitleEditing(false)
                if (e.key === 'Escape') {
                  setTitleEditing(false)
                  setTitleValue(chapter?.title ?? titleValue)
                }
              }}
              style={{ maxWidth: 520 }}
            />
          ) : (
            <div
              className="font-medium text-gray-900 truncate cursor-pointer"
              title="双击编辑标题"
              onDoubleClick={() => setTitleEditing(true)}
            >
              {chapter ? `第${chapter.index}章 · ${titleValue || chapter.title}` : '章节编辑'}
            </div>
          )}
          <div className="text-xs text-gray-500 flex items-center gap-1">
            <CheckCircleOutlined /> 已加载
          </div>
        </div>
      </Header>

      <Content
        style={{
          padding: 16,
          minHeight: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Card size="small" className="mb-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <Steps
              current={activeStep}
              onChange={setActiveStep}
              className="flex-1 min-w-[520px]"
              items={[
                { title: '智能提取' },
                { title: '场景生成' },
                { title: '道具生成' },
                { title: '角色生成' },
                { title: '分镜预览' },
              ]}
            />
            <Space>
              {activeStep > 0 && (
                <Button onClick={() => setActiveStep((s) => Math.max(0, s - 1))}>
                  上一步：{['智能提取', '场景生成', '道具生成', '角色生成', '分镜预览'][activeStep - 1]}
                </Button>
              )}
              {activeStep < 4 ? (
                <Button type="primary" onClick={() => setActiveStep((s) => Math.min(4, s + 1))}>
                  下一步：{['智能提取', '场景生成', '道具生成', '角色生成', '分镜预览'][activeStep + 1]}
                </Button>
              ) : (
                <Button type="primary" onClick={handleFinishPrep}>
                  准备结束
                </Button>
              )}
            </Space>
          </div>
        </Card>

        {activeStep === 0 && (
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12, overflow: 'hidden' }}>
            <Card size="small">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <Space wrap>
                  <Button icon={<FileTextOutlined />} onClick={() => setEditorModalOpen(true)}>
                    编辑原文
                  </Button>
                  <Button type="primary" loading={extracting} icon={<ThunderboltOutlined />} onClick={() => void runExtract('all')}>
                    一键提取全部
                  </Button>
                  <Button
                    loading={creatingAssets}
                    icon={<CheckCircleOutlined />}
                    onClick={() => void batchCreateAssets()}
                    disabled={currentItemsCount.roles + currentItemsCount.scenes + currentItemsCount.props === 0}
                  >
                    一键创建资产
                  </Button>
                  <Button
                    loading={generatingImages}
                    icon={<VideoCameraOutlined />}
                    onClick={() => void batchGenerateAssetImages('character')}
                    disabled={currentItemsCount.roles === 0}
                  >
                    批量生成角色参考图
                  </Button>
                  <Button
                    loading={generatingImages}
                    icon={<VideoCameraOutlined />}
                    onClick={() => void batchGenerateAssetImages('scene')}
                    disabled={currentItemsCount.scenes === 0}
                  >
                    批量生成场景参考图
                  </Button>
                  <span className="text-xs text-gray-500">
                    {currentItemsCount.roles + currentItemsCount.scenes + currentItemsCount.props > 0 ? '已提取，可重新提取' : '尚未提取'}
                  </span>
                </Space>
                {lastImageTasks.length > 0 && (
                  <div className="text-xs text-gray-500 w-full mt-1">
                    最近提交 {lastImageTasks.length} 个参考图任务，提示词已下发（前往分镜工作室或资产页查看出图/抽卡）。
                  </div>
                )}
              </div>
            </Card>

            {/* 左导航 + 右详情 */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 12, overflow: 'hidden' }}>
              {/* 左侧导航 */}
              <Card
                style={{ width: 340, minWidth: 280, maxWidth: 420, height: '100%', overflow: 'hidden', flexShrink: 0 }}
                bodyStyle={{ padding: 12, height: '100%', minHeight: 0, overflow: 'auto' }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="font-medium">提取结果导航</div>
                  <Badge status={extracting ? 'processing' : 'success'} text={extracting ? '提取中…' : '就绪'} />
                </div>
                <Collapse
                  defaultActiveKey={['storyboards']}
                  items={[
                    {
                      key: 'storyboards',
                      label: `原文分镜建议（${currentItemsCount.storyboards}）`,
                      extra: (
                        <Space size="small">
                          <Tooltip title="重新提取">
                            <Button size="small" type="text" icon={<ReloadOutlined />} onClick={() => void runExtract('storyboards')} />
                          </Tooltip>
                        </Space>
                      ),
                      children: extracting ? (
                        <Skeleton active paragraph={{ rows: 4 }} />
                      ) : (
                        <List
                          size="small"
                          dataSource={results.storyboards}
                          locale={{ emptyText: <Empty description="暂无分镜建议" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                          renderItem={(it) => (
                            <List.Item
                              onClick={() => {
                                setSelectedKind('storyboards')
                                setSelectedId(it.id)
                              }}
                              style={{
                                cursor: 'pointer',
                                borderRadius: 10,
                                padding: '8px 10px',
                                background: selectedKind === 'storyboards' && selectedId === it.id ? 'rgba(59,130,246,0.10)' : undefined,
                              }}
                            >
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">
                                  {String(it.index).padStart(2, '0')} · {it.title}
                                </div>
                                <div className="text-xs text-gray-500 truncate">{it.preview}</div>
                              </div>
                            </List.Item>
                          )}
                        />
                      ),
                    },
                    {
                      key: 'roles',
                      label: `角色（${currentItemsCount.roles}）`,
                      children: extracting ? (
                        <Skeleton active paragraph={{ rows: 3 }} />
                      ) : (
                        <List
                          size="small"
                          dataSource={results.roles}
                          locale={{ emptyText: <Empty description="暂无角色" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                          renderItem={(it) => (
                            <List.Item
                              onClick={() => {
                                setSelectedKind('roles')
                                setSelectedId(it.id)
                              }}
                              style={{
                                cursor: 'pointer',
                                borderRadius: 10,
                                padding: '8px 10px',
                                background: selectedKind === 'roles' && selectedId === it.id ? 'rgba(59,130,246,0.10)' : undefined,
                              }}
                            >
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{it.name}</div>
                                <div className="text-xs text-gray-500 truncate">{it.description}</div>
                              </div>
                            </List.Item>
                          )}
                        />
                      ),
                    },
                    {
                      key: 'scenes',
                      label: `场景（${currentItemsCount.scenes}）`,
                      children: extracting ? (
                        <Skeleton active paragraph={{ rows: 3 }} />
                      ) : (
                        <List
                          size="small"
                          dataSource={results.scenes}
                          locale={{ emptyText: <Empty description="暂无场景" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                          renderItem={(it) => (
                            <List.Item
                              onClick={() => {
                                setSelectedKind('scenes')
                                setSelectedId(it.id)
                              }}
                              style={{
                                cursor: 'pointer',
                                borderRadius: 10,
                                padding: '8px 10px',
                                background: selectedKind === 'scenes' && selectedId === it.id ? 'rgba(59,130,246,0.10)' : undefined,
                              }}
                            >
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{it.name}</div>
                                <div className="text-xs text-gray-500 truncate">{it.indoorOutdoor} · {it.time}</div>
                              </div>
                            </List.Item>
                          )}
                        />
                      ),
                    },
                    {
                      key: 'props',
                      label: `道具（${currentItemsCount.props}）`,
                      children: extracting ? (
                        <Skeleton active paragraph={{ rows: 3 }} />
                      ) : (
                        <List
                          size="small"
                          dataSource={results.props}
                          locale={{ emptyText: <Empty description="暂无道具" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                          renderItem={(it) => (
                            <List.Item
                              onClick={() => {
                                setSelectedKind('props')
                                setSelectedId(it.id)
                              }}
                              style={{
                                cursor: 'pointer',
                                borderRadius: 10,
                                padding: '8px 10px',
                                background: selectedKind === 'props' && selectedId === it.id ? 'rgba(59,130,246,0.10)' : undefined,
                              }}
                            >
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{it.name}</div>
                                <div className="text-xs text-gray-500 truncate">出现 {it.count} 次{it.key ? ' · 关键道具' : ''}</div>
                              </div>
                            </List.Item>
                          )}
                        />
                      ),
                    },
                  ]}
                />
              </Card>

              {/* 右侧详情 */}
              <Card style={{ flex: 1, minWidth: 0, height: '100%', overflow: 'hidden' }} bodyStyle={{ padding: 12, height: '100%', minHeight: 0, overflow: 'auto' }}>
                {selectedKind === 'storyboards' && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="font-medium">分镜建议</div>
                      <Space>
                        <Button icon={<MergeCellsOutlined />}>批量操作（Mock）</Button>
                        <Button icon={<PlayCircleOutlined />}>预览（Mock）</Button>
                      </Space>
                    </div>
                    {selectedStoryboard ? (
                      <Card size="small">
                        <div className="text-base font-semibold">
                          {String(selectedStoryboard.index).padStart(2, '0')} · {selectedStoryboard.title}
                          {selectedStoryboard.isTransition && <Tag color="purple" className="ml-2">转场点</Tag>}
                        </div>
                        <Divider />
                        <div className="grid grid-cols-2 gap-3 text-sm">
                          <div><span className="text-gray-500">原文段落：</span>{selectedStoryboard.paragraphRange}</div>
                          <div><span className="text-gray-500">建议时长：</span>{selectedStoryboard.duration}</div>
                          <div><span className="text-gray-500">关键动作：</span>{selectedStoryboard.actions.join('、')}</div>
                          <div><span className="text-gray-500">涉及角色：</span>{selectedStoryboard.roles.join('、')}</div>
                          <div><span className="text-gray-500">涉及场景：</span>{selectedStoryboard.scenes.join('、')}</div>
                          <div><span className="text-gray-500">涉及道具：</span>{selectedStoryboard.props.join('、')}</div>
                        </div>
                        <Divider />
                        <Space wrap>
                          <Button icon={<EditOutlined />}>编辑标题（Mock）</Button>
                          <Button icon={<MergeCellsOutlined />}>合并到上一条（Mock）</Button>
                          <Button icon={<DeleteOutlined />} danger>删除（Mock）</Button>
                          <Button icon={<VideoCameraOutlined />}>标记为转场（Mock）</Button>
                        </Space>
                      </Card>
                    ) : (
                      <Empty description="请从左侧选择一条分镜建议" />
                    )}
                  </div>
                )}

                {selectedKind === 'roles' && (
                  <div className="space-y-3">
                    <div className="font-medium">角色</div>
                    {selectedRole ? (
                      <Card size="small">
                        <div className="flex items-center justify-between">
                          <div className="text-base font-semibold">{selectedRole.name}</div>
                          <Space>
                            <span className="text-sm text-gray-500">主要角色</span>
                            <Switch checked={selectedRole.primary} />
                          </Space>
                        </div>
                        <div className="text-sm text-gray-500 mt-1">首次出现：{selectedRole.firstSeen}</div>
                        <Divider />
                        <div className="text-sm">{selectedRole.description}</div>
                        <div className="mt-2">
                          {selectedRole.aliases.map((a) => (
                            <Tag key={a}>{a}</Tag>
                          ))}
                        </div>
                        <Divider />
                        <Space wrap>
                          <Button>关联资产库角色（Mock）</Button>
                          <Button type="primary">创建新角色资产（Mock）</Button>
                          <Button danger icon={<DeleteOutlined />}>删除（Mock）</Button>
                        </Space>
                      </Card>
                    ) : (
                      <Empty description="请从左侧选择一个角色" />
                    )}
                  </div>
                )}

                {selectedKind === 'scenes' && (
                  <div className="space-y-3">
                    <div className="font-medium">场景</div>
                    {selectedScene ? (
                      <Card size="small">
                        <div className="text-base font-semibold">{selectedScene.name}</div>
                        <div className="text-sm text-gray-500 mt-1">{selectedScene.indoorOutdoor} · {selectedScene.time}</div>
                        <Divider />
                        <div className="flex flex-wrap gap-2">
                          {selectedScene.keywords.map((k) => <Tag key={k} color="blue">{k}</Tag>)}
                        </div>
                        <Divider />
                        <Space wrap>
                          <Button>关联资产库场景（Mock）</Button>
                          <Button type="primary">创建新场景资产（Mock）</Button>
                          <Button danger icon={<DeleteOutlined />}>删除（Mock）</Button>
                        </Space>
                      </Card>
                    ) : (
                      <Empty description="请从左侧选择一个场景" />
                    )}
                  </div>
                )}

                {selectedKind === 'props' && (
                  <div className="space-y-3">
                    <div className="font-medium">道具</div>
                    {selectedProp ? (
                      <Card size="small">
                        <div className="flex items-center gap-2">
                          <div className="text-base font-semibold">{selectedProp.name}</div>
                          {selectedProp.key && <Tag color="gold">关键道具</Tag>}
                        </div>
                        <div className="text-sm text-gray-500 mt-1">出现次数：{selectedProp.count}</div>
                        <Divider />
                        <Space wrap>
                          <Button>关联资产库道具（Mock）</Button>
                          <Button type="primary">创建新道具资产（Mock）</Button>
                          <Button danger icon={<DeleteOutlined />}>删除（Mock）</Button>
                        </Space>
                      </Card>
                    ) : (
                      <Empty description="请从左侧选择一个道具" />
                    )}
                  </div>
                )}
              </Card>
            </div>
          </div>
        )}

        {activeStep === 1 && (
          <Card title="场景生成" style={{ flex: 1, minHeight: 0, overflow: 'auto' }} bodyStyle={{ padding: 12 }}>
            <div className="flex items-center justify-between mb-3">
              <Space>
                <Button type="primary" disabled={selectedSceneIds.length === 0} onClick={() => generateImages('scene')}>
                  批量生成图片（Mock）
                </Button>
                <span className="text-xs text-gray-500">已选 {selectedSceneIds.length} 项</span>
              </Space>
              <Space>
                <Button onClick={() => openAddEntity('scene')}>手动添加</Button>
                <Button onClick={() => openPickFromAssets('scene')}>从资产库添加</Button>
              </Space>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {sceneDrafts.map((s) => (
                <Card
                  key={s.id}
                  size="small"
                  title={
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={selectedSceneIds.includes(s.id)}
                        onChange={(e) =>
                          setSelectedSceneIds((prev) =>
                            e.target.checked ? [...prev, s.id] : prev.filter((x) => x !== s.id),
                          )
                        }
                      />
                      <span className="truncate">{s.name}</span>
                    </div>
                  }
                  extra={
                    <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEditEntity('scene', s.id)}>
                      编辑
                    </Button>
                  }
                >
                  <div className="text-xs text-gray-500 mb-2 line-clamp-2">{s.description || '暂无描述'}</div>
                  <div className="h-32 rounded-md border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-500 text-sm">
                    {s.imageUrl ? '已生成（Mock）' : '未生成'}
                  </div>
                </Card>
              ))}
            </div>
          </Card>
        )}

        {activeStep === 2 && (
          <Card title="道具生成" style={{ flex: 1, minHeight: 0, overflow: 'auto' }} bodyStyle={{ padding: 12 }}>
            <div className="flex items-center justify-between mb-3">
              <Space>
                <Button type="primary" disabled={selectedPropIds.length === 0} onClick={() => generateImages('prop')}>
                  批量生成图片（Mock）
                </Button>
                <span className="text-xs text-gray-500">已选 {selectedPropIds.length} 项</span>
              </Space>
              <Space>
                <Button onClick={() => openAddEntity('prop')}>手动添加</Button>
                <Button onClick={() => openPickFromAssets('prop')}>从资产库添加</Button>
              </Space>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {propDrafts.map((p) => (
                <Card
                  key={p.id}
                  size="small"
                  title={
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={selectedPropIds.includes(p.id)}
                        onChange={(e) =>
                          setSelectedPropIds((prev) =>
                            e.target.checked ? [...prev, p.id] : prev.filter((x) => x !== p.id),
                          )
                        }
                      />
                      <span className="truncate">{p.name}</span>
                    </div>
                  }
                  extra={
                    <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEditEntity('prop', p.id)}>
                      编辑
                    </Button>
                  }
                >
                  <div className="text-xs text-gray-500 mb-2 line-clamp-2">{p.description || '暂无描述'}</div>
                  <div className="h-32 rounded-md border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-500 text-sm">
                    {p.imageUrl ? '已生成（Mock）' : '未生成'}
                  </div>
                </Card>
              ))}
            </div>
          </Card>
        )}

        {activeStep === 3 && (
          <Card title="角色生成" style={{ flex: 1, minHeight: 0, overflow: 'auto' }} bodyStyle={{ padding: 12 }}>
            <div className="flex items-center justify-between mb-3">
              <Space>
                <Button type="primary" disabled={selectedRoleIds.length === 0} onClick={() => generateImages('role')}>
                  批量生成图片（Mock）
                </Button>
                <span className="text-xs text-gray-500">已选 {selectedRoleIds.length} 项</span>
              </Space>
              <Space>
                <Button onClick={() => openAddEntity('role')}>手动添加</Button>
                <Button onClick={() => openPickFromAssets('role')}>从资产库添加</Button>
              </Space>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {roleDrafts.map((r) => (
                <Card
                  key={r.id}
                  size="small"
                  title={
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={selectedRoleIds.includes(r.id)}
                        onChange={(e) =>
                          setSelectedRoleIds((prev) =>
                            e.target.checked ? [...prev, r.id] : prev.filter((x) => x !== r.id),
                          )
                        }
                      />
                      <span className="truncate">{r.name}</span>
                    </div>
                  }
                  extra={
                    <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEditEntity('role', r.id)}>
                      编辑
                    </Button>
                  }
                >
                  <div className="text-xs text-gray-500 mb-2 line-clamp-2">{r.description || '暂无描述'}</div>
                  <div className="h-32 rounded-md border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-500 text-sm">
                    {r.imageUrl ? '已生成（Mock）' : '未生成'}
                  </div>
                </Card>
              ))}
            </div>
          </Card>
        )}

        {activeStep === 4 && (
          <Card title="分镜预览" style={{ flex: 1, minHeight: 0, overflow: 'auto' }} bodyStyle={{ padding: 12 }}>
            <Table<StoryboardDraft>
              rowKey="id"
              dataSource={storyboardDrafts}
              pagination={{ pageSize: 10 }}
              size="small"
              columns={[
                { title: '序号', dataIndex: 'index', key: 'index', width: 80 },
                { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
                { title: '预览', dataIndex: 'preview', key: 'preview', ellipsis: true },
                { title: '段落', dataIndex: 'paragraphRange', key: 'paragraphRange', width: 120 },
                {
                  title: '操作',
                  key: 'action',
                  width: 90,
                  render: (_, record) => (
                    <Button type="link" size="small" onClick={() => openEditStoryboard(record)}>
                      编辑
                    </Button>
                  ),
                },
              ] as TableColumnsType<StoryboardDraft>}
            />
          </Card>
        )}
      </Content>

      <Modal
        title="编辑信息"
        open={editEntityOpen}
        onCancel={() => {
          setEditEntityOpen(false)
          setEditEntityId(null)
        }}
        onOk={saveEditEntity}
        okText="保存"
        width={560}
      >
        <div className="space-y-3">
          <div>
            <span className="text-gray-600 text-sm">名称</span>
            <Input value={editEntityName} onChange={(e) => setEditEntityName(e.target.value)} className="mt-1" />
          </div>
          <div>
            <span className="text-gray-600 text-sm">描述</span>
            <Input.TextArea
              value={editEntityDesc}
              onChange={(e) => setEditEntityDesc(e.target.value)}
              rows={6}
              className="mt-1"
            />
          </div>
        </div>
      </Modal>

      <Modal
        title="手动添加"
        open={addEntityOpen}
        onCancel={() => setAddEntityOpen(false)}
        onOk={addEntity}
        okText="添加"
        width={560}
      >
        <div className="space-y-3">
          <div>
            <span className="text-gray-600 text-sm">名称</span>
            <Input value={addEntityName} onChange={(e) => setAddEntityName(e.target.value)} className="mt-1" />
          </div>
          <div>
            <span className="text-gray-600 text-sm">描述</span>
            <Input.TextArea
              value={addEntityDesc}
              onChange={(e) => setAddEntityDesc(e.target.value)}
              rows={6}
              className="mt-1"
            />
          </div>
        </div>
      </Modal>

      <Modal
        title="从资产库添加（Mock）"
        open={pickFromAssetsOpen}
        onCancel={() => setPickFromAssetsOpen(false)}
        onOk={confirmPickFromAssets}
        okText="添加所选"
        width={560}
      >
        <div className="text-xs text-gray-500 mb-2">当前数据来自本地“已存在集合”的 Mock。</div>
        <Checkbox.Group
          value={pickFromAssetsSelected}
          onChange={(vals) => setPickFromAssetsSelected(vals as string[])}
          className="w-full"
        >
          <div className="space-y-2">
            {(pickFromAssetsKind === 'scene'
              ? existingEntities.scenes
              : pickFromAssetsKind === 'prop'
                ? existingEntities.props
                : existingEntities.roles
            ).map((name) => (
              <div key={name} className="flex items-center justify-between">
                <Checkbox value={name}>{name}</Checkbox>
              </div>
            ))}
          </div>
        </Checkbox.Group>
        {((pickFromAssetsKind === 'scene'
          ? existingEntities.scenes
          : pickFromAssetsKind === 'prop'
            ? existingEntities.props
            : existingEntities.roles
        ).length === 0) && <Empty description="资产库暂无内容（Mock）" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Modal>

      <Modal
        title={editingStoryboard ? `编辑分镜：${editingStoryboard.title}` : '编辑分镜'}
        open={editStoryboardOpen}
        onCancel={() => {
          setEditStoryboardOpen(false)
          setEditingStoryboard(null)
        }}
        onOk={saveStoryboard}
        okText="保存"
        width={640}
      >
        <div className="space-y-3">
          <div>
            <span className="text-gray-600 text-sm">标题</span>
            <Input
              value={editingStoryboard?.title ?? ''}
              onChange={(e) =>
                setEditingStoryboard((prev) => (prev ? { ...prev, title: e.target.value } : prev))
              }
              className="mt-1"
            />
          </div>
          <div>
            <span className="text-gray-600 text-sm">预览</span>
            <Input.TextArea
              value={editingStoryboard?.preview ?? ''}
              onChange={(e) =>
                setEditingStoryboard((prev) => (prev ? { ...prev, preview: e.target.value } : prev))
              }
              rows={5}
              className="mt-1"
            />
          </div>
          <div>
            <span className="text-gray-600 text-sm">段落范围</span>
            <Input
              value={editingStoryboard?.paragraphRange ?? ''}
              onChange={(e) =>
                setEditingStoryboard((prev) => (prev ? { ...prev, paragraphRange: e.target.value } : prev))
              }
              className="mt-1"
            />
          </div>
        </div>
      </Modal>

      <ChapterRawTextEditorModal
        open={editorModalOpen}
        onClose={() => setEditorModalOpen(false)}
        chapterId={chapterId}
        onSaved={(next) => {
          if (typeof next.rawText === 'string') setRawText(next.rawText)
          if (typeof next.condensedText === 'string') setCondensedText(next.condensedText)
        }}
      />

      {/* 提取结果回显浮窗 */}
      <Modal
        title="提取结果"
        open={extractReviewOpen}
        onCancel={() => setExtractReviewOpen(false)}
        width={860}
        footer={
          <Space>
            <Button onClick={() => setExtractReviewOpen(false)}>关闭</Button>
          </Space>
        }
        styles={{ body: { maxHeight: '70vh', overflow: 'auto' } }}
      >
        <Tabs
          activeKey={extractReviewTab}
          onChange={(k) => setExtractReviewTab(k as EntityKind)}
          items={[
            {
              key: 'roles',
              label: `角色（${results.roles.length}）`,
              children: (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs text-gray-500">勾选后可添加到“已存在”集合（本地 Mock）。</div>
                    <Space size="small">
                      <Button size="small" onClick={() => toggleSelectAllNew('roles')}>
                        全选新项
                      </Button>
                      <Button size="small" type="primary" onClick={() => addSelectedEntities('roles')}>
                        添加所选
                      </Button>
                    </Space>
                  </div>
                  <Checkbox.Group
                    value={selectedEntityKeys.roles}
                    onChange={(vals) => setSelectedEntityKeys((prev) => ({ ...prev, roles: vals as string[] }))}
                    className="w-full"
                  >
                    <List
                      dataSource={results.roles}
                      locale={{ emptyText: <Empty description="暂无角色" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                      renderItem={(it) => {
                        const existed = existingSet.roles.has(it.name)
                        return (
                          <List.Item>
                            <div className="flex items-center justify-between w-full">
                              <Checkbox value={it.name}>
                                <span className="font-medium">{it.name}</span>
                                {it.aliases?.length ? (
                                  <span className="text-xs text-gray-500 ml-2">别名：{it.aliases.join('、')}</span>
                                ) : null}
                              </Checkbox>
                              {existed ? <Tag color="default">已存在</Tag> : <Tag color="green">新</Tag>}
                            </div>
                          </List.Item>
                        )
                      }}
                    />
                  </Checkbox.Group>
                </div>
              ),
            },
            {
              key: 'scenes',
              label: `场景（${results.scenes.length}）`,
              children: (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs text-gray-500">勾选后可添加到“已存在”集合（本地 Mock）。</div>
                    <Space size="small">
                      <Button size="small" onClick={() => toggleSelectAllNew('scenes')}>
                        全选新项
                      </Button>
                      <Button size="small" type="primary" onClick={() => addSelectedEntities('scenes')}>
                        添加所选
                      </Button>
                    </Space>
                  </div>
                  <Checkbox.Group
                    value={selectedEntityKeys.scenes}
                    onChange={(vals) => setSelectedEntityKeys((prev) => ({ ...prev, scenes: vals as string[] }))}
                    className="w-full"
                  >
                    <List
                      dataSource={results.scenes}
                      locale={{ emptyText: <Empty description="暂无场景" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                      renderItem={(it) => {
                        const existed = existingSet.scenes.has(it.name)
                        return (
                          <List.Item>
                            <div className="flex items-center justify-between w-full">
                              <Checkbox value={it.name}>
                                <span className="font-medium">{it.name}</span>
                                <span className="text-xs text-gray-500 ml-2">
                                  {it.indoorOutdoor} · {it.time}
                                </span>
                              </Checkbox>
                              {existed ? <Tag color="default">已存在</Tag> : <Tag color="green">新</Tag>}
                            </div>
                          </List.Item>
                        )
                      }}
                    />
                  </Checkbox.Group>
                </div>
              ),
            },
            {
              key: 'props',
              label: `道具（${results.props.length}）`,
              children: (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs text-gray-500">勾选后可添加到“已存在”集合（本地 Mock）。</div>
                    <Space size="small">
                      <Button size="small" onClick={() => toggleSelectAllNew('props')}>
                        全选新项
                      </Button>
                      <Button size="small" type="primary" onClick={() => addSelectedEntities('props')}>
                        添加所选
                      </Button>
                    </Space>
                  </div>
                  <Checkbox.Group
                    value={selectedEntityKeys.props}
                    onChange={(vals) => setSelectedEntityKeys((prev) => ({ ...prev, props: vals as string[] }))}
                    className="w-full"
                  >
                    <List
                      dataSource={results.props}
                      locale={{ emptyText: <Empty description="暂无道具" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                      renderItem={(it) => {
                        const existed = existingSet.props.has(it.name)
                        return (
                          <List.Item>
                            <div className="flex items-center justify-between w-full">
                              <Checkbox value={it.name}>
                                <span className="font-medium">{it.name}</span>
                                <span className="text-xs text-gray-500 ml-2">
                                  出现 {it.count} 次{it.key ? ' · 关键道具' : ''}
                                </span>
                              </Checkbox>
                              {existed ? <Tag color="default">已存在</Tag> : <Tag color="green">新</Tag>}
                            </div>
                          </List.Item>
                        )
                      }}
                    />
                  </Checkbox.Group>
                </div>
              ),
            },
          ]}
        />
      </Modal>
    </Layout>
  )
}

export default ChapterPrep

