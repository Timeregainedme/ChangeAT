import { ArrowRight, Pencil, Trash2 } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { cn } from '../../lib/utils'
import { formatDateTime, getStagePresentation } from './format'
import type { ProjectSummary } from './useProjectSummaries'
import type { ProjectView } from './types'

interface ProjectCardProps {
  project: ProjectView
  summary?: ProjectSummary
  /** 摘要是否仍在加载，用于把「下一步」区域显示成骨架而不是「待推进」。 */
  summaryLoading?: boolean
  onOpen: () => void
  onEdit: () => void
  onDelete: () => void
}

/** 小型计数徽标：把「待确认 / 已就绪 / 生成中」三类数字并排展示。 */
function FlowCount({ count, tone, label }: { count: number; tone: 'pending' | 'ready' | 'running'; label: string }) {
  const dotClass = {
    pending: 'bg-state-pending',
    ready: 'bg-state-ready',
    running: 'bg-run-running',
  }[tone]

  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
      <span className={cn('h-1.5 w-1.5 rounded-full', dotClass)} />
      {label} {count}
    </span>
  )
}

/**
 * 项目卡片。
 *
 * 信息优先级：项目名 → 当前该做什么 → 镜头流量 → 进度与体量。
 * 「下一步」放在中段而不是底部，因为用户扫列表时真正要回答的问题是「现在轮到干什么」。
 */
export function ProjectCard({
  project,
  summary,
  summaryLoading = false,
  onOpen,
  onEdit,
  onDelete,
}: ProjectCardProps) {
  const stage = getStagePresentation(summary?.stageKey)
  const actionLabel = summary?.actionLabel ?? '进入项目'

  return (
    <Card
      className="group flex h-full cursor-pointer flex-col p-4 transition-shadow hover:shadow-popover"
      onClick={onOpen}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[11px] uppercase tracking-wide text-muted-foreground">
            {project.visualStyle} · {project.style || '未设定风格'}
          </p>
          <h3 className="mt-1 truncate text-base font-semibold leading-tight">{project.name}</h3>
        </div>
        <span
          className={cn(
            'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium',
            stage.tone === 'ready'
              ? 'bg-state-ready/15 text-state-ready'
              : 'bg-state-pending/15 text-state-pending',
          )}
        >
          {stage.label}
        </span>
      </div>

      <p className="mt-2 line-clamp-2 min-h-[2.5rem] text-xs leading-5 text-muted-foreground">
        {project.description || '暂无简介'}
      </p>

      <div className="mt-3 rounded-md border border-border bg-muted/50 p-2.5">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">下一步</span>
          <span className="truncate font-medium">{summaryLoading ? '正在分析…' : actionLabel}</span>
        </div>
        <p className="mt-1 truncate text-[11px] text-muted-foreground">
          {summary?.hint ?? '进入项目工作台后继续推进主流程'}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <FlowCount count={summary?.flow?.pendingConfirmShots ?? 0} tone="pending" label="待确认" />
          <FlowCount count={summary?.flow?.readyShots ?? 0} tone="ready" label="已就绪" />
          <FlowCount count={summary?.flow?.generatingShots ?? 0} tone="running" label="生成中" />
        </div>
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>进度</span>
          <span>{project.progress}%</span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-[width]"
            style={{ width: `${Math.min(100, Math.max(0, project.progress))}%` }}
          />
        </div>
      </div>

      <div className="mt-2 text-[11px] text-muted-foreground">
        {project.stats.chapters} 章 · {project.stats.roles} 角色 · {project.stats.scenes} 场景 ·{' '}
        {project.stats.props} 道具
      </div>

      <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-3">
        <span className="truncate text-[11px] text-muted-foreground">
          {formatDateTime(project.updatedAt)}
        </span>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            onClick={(event) => {
              event.stopPropagation()
              onOpen()
            }}
          >
            {actionLabel}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="编辑项目"
            onClick={(event) => {
              event.stopPropagation()
              onEdit()
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="删除项目"
            className="text-muted-foreground hover:text-destructive"
            onClick={(event) => {
              event.stopPropagation()
              onDelete()
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </Card>
  )
}
