/**
 * 列表页文案与格式化工具。
 *
 * 时间格式化只处理本项目实际会遇到的两类输入（ISO 字符串、后端已格式化的字符串），
 * 不使用重量级日期库：列表页只是展示，不需要时区换算能力。
 */
export function formatDateTime(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

/** 把章节准备态映射成「对用户有意义的阶段名 + 用哪一族的颜色」。 */
export interface StagePresentation {
  label: string
  /** state-pending：还需要人工处理；state-ready：已具备进入后续流程的条件。 */
  tone: 'pending' | 'ready'
}

const STAGE_PRESENTATION: Record<string, StagePresentation> = {
  create_first_chapter: { label: '待创建章节', tone: 'pending' },
  edit_raw: { label: '待录入原文', tone: 'pending' },
  extract_shots: { label: '待提取分镜', tone: 'pending' },
  prepare_shots: { label: '待准备镜头', tone: 'pending' },
  shoot: { label: '可进入拍摄', tone: 'ready' },
}

export function getStagePresentation(stageKey: string | undefined): StagePresentation {
  if (!stageKey) return { label: '待推进', tone: 'pending' }
  return STAGE_PRESENTATION[stageKey] ?? { label: '待推进', tone: 'pending' }
}
