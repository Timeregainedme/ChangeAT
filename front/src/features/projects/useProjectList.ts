import { useCallback, useEffect, useState } from 'react'
import { StudioProjectsService } from '../../services/generated'
import type { ProjectRead, ProjectStyle } from '../../services/generated'
import { projects as mockProjects } from '../../mocks/data'
import { toProjectView, type ProjectView } from './types'

const useMock = import.meta.env.VITE_USE_MOCK === 'true'
const PAGE_SIZE = 100

/** 创建 / 编辑项目时提交的字段集合，创建与编辑共用同一份形状。 */
export interface ProjectFormValues {
  name: string
  description: string
  visualStyle: string
  style: string
  seed: number
  unifyStyle: boolean
  defaultVideoRatio: string | null
}

/** 生成项目 ID：优先用 crypto.randomUUID，非安全上下文回退到时间戳 + 随机数。 */
function newProjectId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `p_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

/**
 * 项目列表的数据层。
 *
 * 把「取数 + 增删改 + 错误」收口在一个 hook 里，页面只负责展示。
 * 后端仍是分页接口，这里一次性拉 100 条：当前团队的项目量远小于这个量级，
 * 做客户端搜索比每次输入都请求一次更快；超过后再补服务端搜索。
 */
export function useProjectList() {
  const [projects, setProjects] = useState<ProjectView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (useMock) {
        setProjects((mockProjects as unknown as ProjectRead[]).map(toProjectView))
        return
      }
      const res = await StudioProjectsService.listProjectsApiV1StudioProjectsGet({
        page: 1,
        pageSize: PAGE_SIZE,
      })
      setProjects((res.data?.items ?? []).map(toProjectView))
    } catch {
      setProjects([])
      setError('项目列表加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  /** 创建项目：成功后直接把新项目插入列表头部，避免整页重新拉取。 */
  const createProject = useCallback(async (values: ProjectFormValues): Promise<ProjectView> => {
    const res = await StudioProjectsService.createProjectApiV1StudioProjectsPost({
      requestBody: {
        id: newProjectId(),
        name: values.name,
        description: values.description,
        style: values.style as ProjectStyle,
        visual_style: values.visualStyle as never,
        seed: values.seed,
        unify_style: values.unifyStyle,
        default_video_ratio: values.defaultVideoRatio,
        progress: 0,
      },
    })
    const created = res.data
    if (!created) throw new Error('创建失败：服务端没有返回项目')
    const view = toProjectView(created)
    setProjects((prev) => [view, ...prev])
    return view
  }, [])

  /** 更新项目：只回填被改动的项目，保留列表顺序。 */
  const updateProject = useCallback(
    async (projectId: string, values: ProjectFormValues): Promise<ProjectView> => {
      const res = await StudioProjectsService.updateProjectApiV1StudioProjectsProjectIdPatch({
        projectId,
        requestBody: {
          name: values.name,
          description: values.description,
          style: values.style as ProjectStyle,
          visual_style: values.visualStyle as never,
          seed: values.seed,
          unify_style: values.unifyStyle,
          default_video_ratio: values.defaultVideoRatio,
        },
      })
      const updated = res.data
      if (!updated) throw new Error('更新失败：服务端没有返回项目')
      const view = toProjectView(updated)
      setProjects((prev) => prev.map((item) => (item.id === view.id ? view : item)))
      return view
    },
    [],
  )

  /** 删除项目：失败时保留本地状态，避免出现「界面删了、服务端还在」。 */
  const removeProject = useCallback(async (projectId: string) => {
    await StudioProjectsService.deleteProjectApiV1StudioProjectsProjectIdDelete({ projectId })
    setProjects((prev) => prev.filter((item) => item.id !== projectId))
  }, [])

  return {
    projects,
    loading,
    error,
    reload,
    createProject,
    updateProject,
    removeProject,
  }
}
