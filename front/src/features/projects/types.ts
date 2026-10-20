import type { ProjectRead } from '../../services/generated'

/**
 * 列表页使用的项目视图模型。
 *
 * 保留后端字段的语义，但把「嵌套在 stats 里的弱类型数字」摊平成强类型，
 * 避免每个组件里都写一遍 `typeof stats.x === 'number'` 的防御代码。
 */
export interface ProjectView {
  id: string
  name: string
  description: string
  style: string
  seed: number
  unifyStyle: boolean
  progress: number
  stats: {
    chapters: number
    roles: number
    scenes: number
    props: number
  }
  /** 展示用时间戳，后端放在 stats 里，缺失时回退到当前时间。 */
  updatedAt: string
  visualStyle: string
  defaultVideoRatio: string | null
}

/** 从后端返回的项目对象转换出视图模型，集中处理字段缺失与类型收窄。 */
export function toProjectView(p: ProjectRead): ProjectView {
  const stats = (p.stats ?? {}) as Record<string, unknown>
  const num = (key: string) => {
    const v = stats[key]
    return typeof v === 'number' && Number.isFinite(v) ? v : 0
  }

  const updatedAt =
    (typeof stats.updated_at === 'string' && stats.updated_at) ||
    (typeof stats.updatedAt === 'string' && stats.updatedAt) ||
    new Date().toISOString()

  return {
    id: p.id,
    name: p.name,
    description: p.description ?? '',
    style: p.style ?? '',
    seed: p.seed ?? 0,
    unifyStyle: p.unify_style ?? true,
    progress: p.progress ?? 0,
    stats: {
      chapters: num('chapters'),
      roles: num('roles'),
      scenes: num('scenes'),
      props: num('props'),
    },
    updatedAt,
    visualStyle: p.visual_style ?? '现实',
    defaultVideoRatio: p.default_video_ratio ?? null,
  }
}

/** 项目整体完成度分档，只用于卡片上的弱提示，不代表业务状态机。 */
export type ProjectProgressBand = 'draft' | 'inProgress' | 'completed'

export function getProgressBand(progress: number): ProjectProgressBand {
  if (progress >= 90) return 'completed'
  if (progress <= 5) return 'draft'
  return 'inProgress'
}
