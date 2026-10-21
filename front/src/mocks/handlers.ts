import { http, HttpResponse } from 'msw'
import type { Project, Agent, Provider, Model, ModelSettings, Chapter } from './data'
import {
  agents as initialAgents,
  assets,
  chapters,
  defaultModelSettings,
  files,
  llmModels,
  projects as initialProjects,
  providers as initialProviders,
  promptTemplates,
  shotDetails,
  shots,
  timelineClips,
} from './data'

// 可变的项目列表，支持创建/编辑/删除（会话内生效）
let projectsList: Project[] = [...initialProjects]
let chaptersList: Chapter[] = [...chapters]
let agentsList: Agent[] = [...initialAgents]
let providersList: Provider[] = [...initialProviders]
let modelsList: Model[] = [...llmModels]
let modelSettingsStore: ModelSettings = { ...defaultModelSettings }

function nextProjectId(): string {
  const max = projectsList.reduce((m, p) => {
    const n = parseInt(p.id.replace(/\D/g, ''), 10)
    return isNaN(n) ? m : Math.max(m, n)
  }, 0)
  return `p${max + 1}`
}

function makePagination<T>(items: T[], page: number, pageSize: number) {
  const total = items.length
  const safePageSize = pageSize > 0 ? pageSize : 10
  const maxPage = Math.max(1, Math.ceil(total / safePageSize))
  const safePage = Math.min(Math.max(page, 1), maxPage)
  const start = (safePage - 1) * safePageSize
  const pageItems = items.slice(start, start + safePageSize)
  return {
    items: pageItems,
    pagination: {
      page: safePage,
      page_size: safePageSize,
      total,
      max_page: maxPage,
    },
  }
}

function ok<T>(data: T, status = 200, message = 'OK') {
  return HttpResponse.json(
    {
      code: status,
      message,
      data,
    },
    { status },
  )
}

function notFound(message = 'Not found') {
  return HttpResponse.json(
    {
      code: 404,
      message,
      data: null,
    },
    { status: 404 },
  )
}

function toProjectRead(p: Project) {
  return {
    id: p.id,
    name: p.name,
    description: p.description,
    style: p.style,
    seed: p.seed,
    unify_style: p.unifyStyle,
    progress: p.progress,
    stats: p.stats,
  }
}

function toChapterRead(c: Chapter) {
  return {
    id: c.id,
    project_id: c.projectId,
    index: c.index,
    title: c.title,
    summary: c.summary,
    storyboard_count: c.storyboardCount,
    status: c.status,
  }
}

/**
 * 看板用的可变镜头列表。
 *
 * 把 mock 的 Shot 映射成后端 ShotRead 的形状（下划线字段），
 * 这样页面代码不需要为 mock 走分支——分支越多，真实路径越难被覆盖。
 */
const shotsList = shots.map((s) => ({
  id: s.id,
  chapter_id: s.chapterId,
  index: s.index,
  title: s.title,
  thumbnail: s.thumbnail,
  status: s.status,
  skip_extraction: false,
  script_excerpt: s.scriptExcerpt,
  // 待确认镜头模拟「已提取、各剩 1 条待确认」，让批量确认向导有真实分组可展示
  extraction:
    s.status === 'ready'
      ? { state: 'extracted_resolved', pending_asset_count: 0, pending_dialogue_count: 0 }
      : { state: 'extracted_pending', pending_asset_count: 1, pending_dialogue_count: 1 },
}))

/** 候选 mock：每个待确认镜头各一条资产候选与一条对白候选。 */
const assetCandidatesByShot: Record<string, Array<Record<string, unknown>>> = {}
const dialogueCandidatesByShot: Record<string, Array<Record<string, unknown>>> = {}

/** 按镜头懒生成候选：待确认镜头各一条，ready 镜头没有。 */
function ensureCandidates() {
  for (const shot of shotsList) {
    if (shot.status === 'ready') continue
    assetCandidatesByShot[shot.id] ??= [
      {
        id: Number(shot.id.replace(/\D/g, '')) * 10 + 1,
        shot_id: shot.id,
        candidate_type: 'character',
        candidate_name: '候选角色',
        candidate_status: 'pending',
        source: 'mock',
      },
    ]
    dialogueCandidatesByShot[shot.id] ??= [
      {
        id: Number(shot.id.replace(/\D/g, '')) * 10 + 2,
        shot_id: shot.id,
        candidate_status: 'pending',
        text: '候选台词',
      },
    ]
  }
}
ensureCandidates()

export const handlers = [
  // ====== StudioProjectsService /api/v1/studio/projects ======
  http.get('/api/v1/studio/projects', ({ request }) => {
    const url = new URL(request.url)
    const q = url.searchParams.get('q')?.trim()
    const page = Number(url.searchParams.get('page') ?? '1') || 1
    const pageSize = Number(url.searchParams.get('page_size') ?? '10') || 10

    let list = projectsList
    if (q) {
      list = list.filter(
        (p) =>
          p.name.includes(q) ||
          (p.description && p.description.includes(q)),
      )
    }

    const paged = makePagination(list.map(toProjectRead), page, pageSize)
    return ok(paged)
  }),

  http.post('/api/v1/studio/projects', async ({ request }) => {
    const body = (await request.json()) as Partial<Project> & {
      id?: string
      name?: string
      description?: string
      style?: Project['style']
      seed?: number
      unify_style?: boolean
      progress?: number
      stats?: Project['stats']
    }

    const id = body.id || nextProjectId()
    const now = new Date().toISOString().slice(0, 16).replace('T', ' ')
    const newProject: Project = {
      id,
      name: body.name ?? '未命名项目',
      description: body.description ?? '',
      style: (body.style as Project['style']) ?? '现实主义',
      seed: typeof body.seed === 'number' ? body.seed : Math.floor(Math.random() * 99999),
      unifyStyle: typeof body.unify_style === 'boolean' ? body.unify_style : true,
      progress: typeof body.progress === 'number' ? body.progress : 0,
      stats: body.stats ?? { chapters: 0, roles: 0, scenes: 0, props: 0 },
      updatedAt: now,
    }

    projectsList = [...projectsList, newProject]
    return ok(toProjectRead(newProject), 200, 'Created')
  }),

  http.get('/api/v1/studio/projects/:project_id', ({ params }) => {
    const { project_id } = params as { project_id: string }
    const project = projectsList.find((p) => p.id === project_id)
    if (!project) return notFound('项目不存在')
    return ok(toProjectRead(project))
  }),

  http.patch('/api/v1/studio/projects/:project_id', async ({ params, request }) => {
    const { project_id } = params as { project_id: string }
    const idx = projectsList.findIndex((p) => p.id === project_id)
    if (idx === -1) return notFound('项目不存在')

    const body = (await request.json()) as Partial<{
      name: string
      description: string
      style: Project['style']
      seed: number
      unify_style: boolean
      progress: number
      stats: Project['stats']
    }>

    const now = new Date().toISOString().slice(0, 16).replace('T', ' ')
    const current = projectsList[idx]
    const updated: Project = {
      ...current,
      name: body.name ?? current.name,
      description: body.description ?? current.description,
      style: (body.style as Project['style']) ?? current.style,
      seed: typeof body.seed === 'number' ? body.seed : current.seed,
      unifyStyle:
        typeof body.unify_style === 'boolean' ? body.unify_style : current.unifyStyle,
      progress:
        typeof body.progress === 'number' ? body.progress : current.progress,
      stats:
        (body.stats as Project['stats']) && typeof body.stats === 'object'
          ? (body.stats as Project['stats'])
          : current.stats,
      updatedAt: now,
    }

    projectsList[idx] = updated
    return ok(toProjectRead(updated))
  }),

  http.delete('/api/v1/studio/projects/:project_id', ({ params }) => {
    const { project_id } = params as { project_id: string }
    const idx = projectsList.findIndex((p) => p.id === project_id)
    if (idx === -1) return notFound('项目不存在')
    projectsList = projectsList.filter((p) => p.id !== project_id)
    return ok(null, 200, 'Deleted')
  }),

  // ====== StudioChaptersService /api/v1/studio/chapters ======
  http.get('/api/v1/studio/chapters', ({ request }) => {
    const url = new URL(request.url)
    const projectId = url.searchParams.get('project_id') ?? undefined
    const q = url.searchParams.get('q')?.trim()
    const page = Number(url.searchParams.get('page') ?? '1') || 1
    const pageSize = Number(url.searchParams.get('page_size') ?? '10') || 10

    let list = chaptersList
    if (projectId) {
      list = list.filter((c) => c.projectId === projectId)
    }
    if (q) {
      list = list.filter(
        (c) =>
          c.title.includes(q) ||
          (c.summary && c.summary.includes(q)),
      )
    }

    const paged = makePagination(list.map(toChapterRead), page, pageSize)
    return ok(paged)
  }),

  http.post('/api/v1/studio/chapters', async ({ request }) => {
    const body = (await request.json()) as Partial<{
      id: string
      project_id: string
      index: number
      title: string
      summary?: string
      storyboard_count?: number
      status?: Chapter['status']
    }>

    if (!body.project_id || !body.title) {
      return HttpResponse.json(
        { code: 422, message: 'project_id 和 title 为必填', data: null },
        { status: 422 },
      )
    }

    const id =
      body.id ||
      `c_${Date.now()}_${Math.random().toString(16).slice(2)}`
    const nextIndex =
      typeof body.index === 'number'
        ? body.index
        : (chaptersList
            .filter((c) => c.projectId === body.project_id)
            .reduce((max, c) => Math.max(max, c.index), 0) || 0) + 1

    const now = new Date().toISOString()
    const newChapter: Chapter = {
      id,
      projectId: body.project_id,
      index: nextIndex,
      title: body.title,
      summary: body.summary ?? '',
      storyboardCount: body.storyboard_count ?? 0,
      status: body.status ?? 'draft',
      updatedAt: now,
    }

    chaptersList = [...chaptersList, newChapter]
    return ok(toChapterRead(newChapter), 200, 'Created')
  }),

  http.get('/api/v1/studio/chapters/:chapter_id', ({ params }) => {
    const { chapter_id } = params as { chapter_id: string }
    const chapter = chaptersList.find((c) => c.id === chapter_id)
    if (!chapter) return notFound('章节不存在')
    return ok(toChapterRead(chapter))
  }),

  http.patch('/api/v1/studio/chapters/:chapter_id', async ({ params, request }) => {
    const { chapter_id } = params as { chapter_id: string }
    const idx = chaptersList.findIndex((c) => c.id === chapter_id)
    if (idx === -1) return notFound('章节不存在')

    const body = (await request.json()) as Partial<{
      project_id: string | null
      index: number | null
      title: string | null
      summary: string | null
      storyboard_count: number | null
      status: Chapter['status'] | null
    }>

    const current = chaptersList[idx]
    const updated: Chapter = {
      ...current,
      projectId:
        typeof body.project_id === 'string'
          ? body.project_id
          : current.projectId,
      index:
        typeof body.index === 'number'
          ? body.index
          : current.index,
      title:
        typeof body.title === 'string'
          ? body.title
          : current.title,
      summary:
        typeof body.summary === 'string'
          ? body.summary
          : current.summary,
      storyboardCount:
        typeof body.storyboard_count === 'number'
          ? body.storyboard_count
          : current.storyboardCount,
      status:
        (body.status as Chapter['status']) ?? current.status,
      updatedAt: new Date().toISOString(),
    }

    chaptersList[idx] = updated
    return ok(toChapterRead(updated))
  }),

  http.delete('/api/v1/studio/chapters/:chapter_id', ({ params }) => {
    const { chapter_id } = params as { chapter_id: string }
    const idx = chaptersList.findIndex((c) => c.id === chapter_id)
    if (idx === -1) return notFound('章节不存在')
    chaptersList = chaptersList.filter((c) => c.id !== chapter_id)
    return ok(null, 200, 'Deleted')
  }),

  // 项目列表
  http.get('/api/projects', () => {
    return HttpResponse.json(projectsList, { status: 200 })
  }),

  // 单个项目详情
  http.get('/api/projects/:projectId', ({ params }) => {
    const { projectId } = params as { projectId: string }
    const project = projectsList.find((p) => p.id === projectId)
    if (!project) {
      return HttpResponse.json({ message: '项目不存在' }, { status: 404 })
    }
    return HttpResponse.json(project, { status: 200 })
  }),

  // 创建项目
  http.post('/api/projects', async ({ request }) => {
    const body = (await request.json()) as Partial<Project> & { name: string; description?: string; style?: string; seed?: number; unifyStyle?: boolean }
    const id = nextProjectId()
    const now = new Date().toISOString().slice(0, 16).replace('T', ' ')
    const newProject: Project = {
      id,
      name: body.name ?? '未命名项目',
      description: body.description ?? '',
      style: (body.style as Project['style']) ?? '现实主义',
      seed: typeof body.seed === 'number' ? body.seed : Math.floor(Math.random() * 99999),
      unifyStyle: body.unifyStyle ?? true,
      progress: 0,
      stats: { chapters: 0, roles: 0, scenes: 0, props: 0 },
      updatedAt: now,
    }
    projectsList = [...projectsList, newProject]
    return HttpResponse.json(newProject, { status: 201 })
  }),

  // 更新项目
  http.put('/api/projects/:projectId', async ({ params, request }) => {
    const { projectId } = params as { projectId: string }
    const idx = projectsList.findIndex((p) => p.id === projectId)
    if (idx === -1) return HttpResponse.json({ message: '项目不存在' }, { status: 404 })
    const body = (await request.json()) as Partial<Project>
    const now = new Date().toISOString().slice(0, 16).replace('T', ' ')
    projectsList = projectsList.map((p, i) =>
      i === idx
        ? { ...p, ...body, id: p.id, updatedAt: now }
        : p
    )
    return HttpResponse.json(projectsList[idx], { status: 200 })
  }),

  // 删除项目
  http.delete('/api/projects/:projectId', ({ params }) => {
    const { projectId } = params as { projectId: string }
    const idx = projectsList.findIndex((p) => p.id === projectId)
    if (idx === -1) return HttpResponse.json({ message: '项目不存在' }, { status: 404 })
    projectsList = projectsList.filter((p) => p.id !== projectId)
    return new HttpResponse(null, { status: 204 })
  }),

  // 项目下章节列表
  http.get('/api/projects/:projectId/chapters', ({ params }) => {
    const { projectId } = params as { projectId: string }
    const list = chapters.filter((c) => c.projectId === projectId)
    return HttpResponse.json(list, { status: 200 })
  }),

  // 某章节的分镜列表
  http.get('/api/chapters/:chapterId/shots', ({ params }) => {
    const { chapterId } = params as { chapterId: string }
    const list = shots.filter((s) => s.chapterId === chapterId)
    return HttpResponse.json(list, { status: 200 })
  }),

  // 单个分镜详情（镜头属性）
  http.get('/api/shots/:shotId', ({ params }) => {
    const { shotId } = params as { shotId: string }
    const detail = shotDetails.find((s) => s.id === shotId)
    if (!detail) {
      return HttpResponse.json({ message: '分镜不存在' }, { status: 404 })
    }
    return HttpResponse.json(detail, { status: 200 })
  }),

  // 资产列表（可通过查询参数过滤）
  http.get('/api/assets', ({ request }) => {
    const url = new URL(request.url)
    const type = url.searchParams.get('type')
    const list = type ? assets.filter((a) => a.type === type) : assets
    return HttpResponse.json(list, { status: 200 })
  }),

  // 提示词模板列表
  http.get('/api/prompts/templates', () => {
    return HttpResponse.json(promptTemplates, { status: 200 })
  }),

  // 文件列表
  http.get('/api/files', () => {
    return HttpResponse.json(files, { status: 200 })
  }),

  // 某项目的时间线数据
  http.get('/api/projects/:projectId/timeline', () => {
    return HttpResponse.json(timelineClips, { status: 200 })
  }),

  // Agent 列表
  http.get('/api/agents', () => {
    return HttpResponse.json(agentsList, { status: 200 })
  }),

  // 单个 Agent 详情
  http.get('/api/agents/:id', ({ params }) => {
    const { id } = params as { id: string }
    const agent = agentsList.find((a) => a.id === id)
    if (!agent) return HttpResponse.json({ message: 'Agent 不存在' }, { status: 404 })
    return HttpResponse.json(agent, { status: 200 })
  }),

  // 创建 Agent
  http.post('/api/agents', async ({ request }) => {
    const body = (await request.json()) as Partial<Agent> & { name: string; type: Agent['type']; description?: string }
    const id = `agent${Date.now()}`
    const now = new Date().toISOString().slice(0, 10)
    const newAgent: Agent = {
      id,
      name: body.name ?? '未命名 Agent',
      type: body.type ?? 'other',
      description: body.description ?? '',
      isDefault: false,
      version: 'v1.0',
      updatedAt: now,
      createdAt: now,
      createdBy: 'extreme',
      updatedBy: 'extreme',
    }
    agentsList = [...agentsList, newAgent]
    return HttpResponse.json(newAgent, { status: 201 })
  }),

  // 更新 Agent（含设置默认）
  http.put('/api/agents/:id', async ({ params, request }) => {
    const { id } = params as { id: string }
    const idx = agentsList.findIndex((a) => a.id === id)
    if (idx === -1) return HttpResponse.json({ message: 'Agent 不存在' }, { status: 404 })
    const body = (await request.json()) as Partial<Agent>
    const now = new Date().toISOString().slice(0, 10)
    const updated = { ...agentsList[idx], ...body, id: agentsList[idx].id, updatedAt: now }
    if (body.isDefault === true) {
      agentsList = agentsList.map((a) =>
        a.type === updated.type && a.id !== id ? { ...a, isDefault: false } : a
      )
      agentsList[idx] = updated
    } else {
      agentsList = agentsList.map((a, i) => (i === idx ? updated : a))
    }
    return HttpResponse.json(agentsList[idx], { status: 200 })
  }),

  // 删除 Agent
  http.delete('/api/agents/:id', ({ params }) => {
    const { id } = params as { id: string }
    const idx = agentsList.findIndex((a) => a.id === id)
    if (idx === -1) return HttpResponse.json({ message: 'Agent 不存在' }, { status: 404 })
    agentsList = agentsList.filter((a) => a.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  // 供应商列表
  http.get('/api/models/providers', () => {
    return HttpResponse.json(providersList, { status: 200 })
  }),
  http.get('/api/models/providers/:id', ({ params }) => {
    const { id } = params as { id: string }
    const p = providersList.find((x) => x.id === id)
    if (!p) return HttpResponse.json({ message: '供应商不存在' }, { status: 404 })
    return HttpResponse.json(p, { status: 200 })
  }),
  http.post('/api/models/providers', async ({ request }) => {
    const body = (await request.json()) as Partial<Provider> & { name: string; base_url: string }
    const id = `prov${Date.now()}`
    const newP: Provider = {
      id,
      name: body.name ?? '未命名',
      base_url: body.base_url ?? '',
      description: body.description ?? '',
      status: body.status ?? 'active',
      created_by: 'extreme',
    }
    providersList = [...providersList, newP]
    return HttpResponse.json(newP, { status: 201 })
  }),
  http.put('/api/models/providers/:id', async ({ params, request }) => {
    const { id } = params as { id: string }
    const idx = providersList.findIndex((p) => p.id === id)
    if (idx === -1) return HttpResponse.json({ message: '供应商不存在' }, { status: 404 })
    const body = (await request.json()) as Partial<Provider>
    providersList = providersList.map((p, i) =>
      i === idx ? { ...p, ...body, id: p.id } : p
    )
    return HttpResponse.json(providersList[idx], { status: 200 })
  }),
  http.delete('/api/models/providers/:id', ({ params }) => {
    const { id } = params as { id: string }
    const idx = providersList.findIndex((p) => p.id === id)
    if (idx === -1) return HttpResponse.json({ message: '供应商不存在' }, { status: 404 })
    providersList = providersList.filter((p) => p.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  // 模型列表
  http.get('/api/models/list', () => {
    return HttpResponse.json(modelsList, { status: 200 })
  }),
  http.get('/api/models/list/:id', ({ params }) => {
    const { id } = params as { id: string }
    const m = modelsList.find((x) => x.id === id)
    if (!m) return HttpResponse.json({ message: '模型不存在' }, { status: 404 })
    return HttpResponse.json(m, { status: 200 })
  }),
  http.post('/api/models/list', async ({ request }) => {
    const body = (await request.json()) as Partial<Model> & { name: string; category: Model['category']; provider_id: string }
    const id = `model${Date.now()}`
    const newM: Model = {
      id,
      name: body.name ?? '未命名',
      category: body.category ?? 'text',
      provider_id: body.provider_id ?? '',
      params: body.params ?? {},
      description: body.description ?? '',
      is_default: body.is_default ?? false,
      created_by: 'extreme',
    }
    if (newM.is_default) {
      modelsList.forEach((m) => {
        if (m.category === newM.category && m.id !== newM.id) (m as Model).is_default = false
      })
    }
    modelsList = [...modelsList, newM]
    return HttpResponse.json(newM, { status: 201 })
  }),
  http.put('/api/models/list/:id', async ({ params, request }) => {
    const { id } = params as { id: string }
    const idx = modelsList.findIndex((m) => m.id === id)
    if (idx === -1) return HttpResponse.json({ message: '模型不存在' }, { status: 404 })
    const body = (await request.json()) as Partial<Model>
    const updated = { ...modelsList[idx], ...body, id: modelsList[idx].id }
    if (body.is_default === true) {
      modelsList = modelsList.map((m) =>
        m.category === updated.category && m.id !== id ? { ...m, is_default: false } : m
      )
      modelsList[idx] = updated
    } else {
      modelsList = modelsList.map((m, i) => (i === idx ? updated : m))
    }
    return HttpResponse.json(modelsList[idx], { status: 200 })
  }),
  http.delete('/api/models/list/:id', ({ params }) => {
    const { id } = params as { id: string }
    const idx = modelsList.findIndex((m) => m.id === id)
    if (idx === -1) return HttpResponse.json({ message: '模型不存在' }, { status: 404 })
    modelsList = modelsList.filter((m) => m.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  // ====== StudioShotsService /api/v1/studio/shots ======
  // 看板需要「列表 + 运行时摘要 + 准备度 + 局部更新」四类接口，
  // 之前这些都没 mock，导致看板在 mock 模式下必然白屏，只能对着测试库验证。
  http.get('/api/v1/studio/shots/runtime-summary', () => ok([])),

  http.get('/api/v1/studio/shots', ({ request }) => {
    const url = new URL(request.url)
    const chapterId = url.searchParams.get('chapter_id') ?? ''
    const page = Number(url.searchParams.get('page') ?? '1') || 1
    const pageSize = Number(url.searchParams.get('page_size') ?? '10') || 10
    const list = shotsList.filter((s) => s.chapter_id === chapterId)
    return ok(makePagination(list, page, pageSize))
  }),

  http.get('/api/v1/studio/shots/:shot_id/video-readiness', ({ params }) => {
    const { shot_id } = params as { shot_id: string }
    return ok({
      shot_id,
      reference_mode: 'none',
      ready: false,
      checks: [
        { key: 'extracted', ok: false, message: '尚未执行信息提取，请先提取或将镜头标记为无需提取' },
        { key: 'duration', ok: true, message: '镜头时长已配置' },
      ],
    })
  }),

  http.get('/api/v1/studio/shots/:shot_id/extracted-candidates', ({ params }) => {
    const { shot_id } = params as { shot_id: string }
    return ok(assetCandidatesByShot[shot_id] ?? [])
  }),

  http.get('/api/v1/studio/shots/:shot_id/extracted-dialogue-candidates', ({ params }) => {
    const { shot_id } = params as { shot_id: string }
    return ok(dialogueCandidatesByShot[shot_id] ?? [])
  }),

  http.patch('/api/v1/studio/shots/extracted-candidates/:candidate_id/ignore', () => ok({})),
  http.patch('/api/v1/studio/shots/extracted-dialogue-candidates/:candidate_id/accept', () => ok({})),
  http.patch('/api/v1/studio/shots/extracted-dialogue-candidates/:candidate_id/ignore', () => ok({})),

  http.patch('/api/v1/studio/shots/:shot_id', async ({ params, request }) => {
    const { shot_id } = params as { shot_id: string }
    const body = (await request.json()) as {
      title?: string
      script_excerpt?: string
      skip_extraction?: boolean
    }
    const target = shotsList.find((s) => s.id === shot_id)
    if (!target) return HttpResponse.json({ code: 404, message: '镜头不存在', data: null }, { status: 404 })

    if (typeof body.title === 'string') target.title = body.title
    if (typeof body.script_excerpt === 'string') target.script_excerpt = body.script_excerpt
    if (typeof body.skip_extraction === 'boolean') target.skip_extraction = body.skip_extraction
    return ok(target)
  }),

  // 模型全局设置
  http.get('/api/models/settings', () => {
    return HttpResponse.json(modelSettingsStore, { status: 200 })
  }),
  http.put('/api/models/settings', async ({ request }) => {
    const body = (await request.json()) as Partial<ModelSettings>
    modelSettingsStore = { ...modelSettingsStore, ...body }
    return HttpResponse.json(modelSettingsStore, { status: 200 })
  }),
]


