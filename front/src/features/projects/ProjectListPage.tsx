import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderPlus, Search, X } from 'lucide-react'
import { Button } from '../../components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { cn } from '../../lib/utils'
import { useProjectStyleOptions } from '../../pages/aiStudio/project/useProjectStyleOptions'
import { ensureHasShotsBeforeShooting } from '../../pages/aiStudio/project/ProjectWorkbench/ensureHasShotsBeforeShooting'
import {
  getChapterBoardPath,
  getChapterShotsPath,
} from '../../pages/aiStudio/project/ProjectWorkbench/routes'
import { ProjectCard } from '../../features/projects/ProjectCard'
import { ProjectFormDialog } from '../../features/projects/ProjectFormDialog'
import { useProjectList, type ProjectFormValues } from '../../features/projects/useProjectList'
import { useProjectSummaries, type ProjectSummary } from '../../features/projects/useProjectSummaries'
import type { ProjectView } from '../../features/projects/types'

type FilterKey = 'all' | 'editRaw' | 'extractShots' | 'prepareShots' | 'generating' | 'ready'
type SortKey = 'updatedAt' | 'name' | 'chapters'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'editRaw', label: '待录入原文' },
  { key: 'extractShots', label: '待提取分镜' },
  { key: 'prepareShots', label: '待准备镜头' },
  { key: 'generating', label: '生成中' },
  { key: 'ready', label: '可推进' },
]

/** 判断项目是否命中某个筛选条件：阶段类看摘要，流量类看镜头统计。 */
function matchesFilter(
  filter: FilterKey,
  summary: ProjectSummary | undefined,
): boolean {
  if (filter === 'all') return true
  if (!summary) return false
  if (filter === 'editRaw') {
    return summary.stageKey === 'edit_raw' || summary.stageKey === 'create_first_chapter'
  }
  if (filter === 'extractShots') return summary.stageKey === 'extract_shots'
  if (filter === 'prepareShots') return summary.stageKey === 'prepare_shots'
  if (filter === 'generating') return (summary.flow?.generatingShots ?? 0) > 0
  if (filter === 'ready') return (summary.flow?.readyShots ?? 0) > 0
  return true
}

/**
 * 项目列表页。
 *
 * 这是第一张完全用新设计系统重写的页面，也是判断「新前端是否更好用」的样板：
 * 卡片上直接回答「现在该做什么」，把原来要进项目才知道的下一步提到列表层。
 */
export function ProjectListPage() {
  const navigate = useNavigate()
  const { projects, loading, error, createProject, updateProject, removeProject } = useProjectList()
  const { summaries, loading: summariesLoading } = useProjectSummaries(projects)
  const { options, videoRatioOptions, defaultVideoRatio } = useProjectStyleOptions()

  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<FilterKey>('all')
  const [sortKey, setSortKey] = useState<SortKey>('updatedAt')
  const [dialogMode, setDialogMode] = useState<'create' | 'edit' | null>(null)
  const [editingProject, setEditingProject] = useState<ProjectView | null>(null)
  const [pendingDelete, setPendingDelete] = useState<ProjectView | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const visibleProjects = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    const filtered = projects.filter((project) => {
      if (keyword) {
        const hit =
          project.name.toLowerCase().includes(keyword) ||
          project.description.toLowerCase().includes(keyword)
        if (!hit) return false
      }
      return matchesFilter(filter, summaries[project.id])
    })

    return [...filtered].sort((a, b) => {
      if (sortKey === 'name') return a.name.localeCompare(b.name)
      if (sortKey === 'chapters') return b.stats.chapters - a.stats.chapters
      return String(b.updatedAt).localeCompare(String(a.updatedAt))
    })
  }, [projects, search, filter, summaries, sortKey])

  /**
   * 进入项目，并直达当前该做的那一步。
   *
   * 列表上的主按钮文案来自章节准备态，所以点击行为必须与文案一致：
   * 显示「提取分镜」却跳到工作台首页，是最容易让新人迷路的地方。
   */
  const openProject = (project: ProjectView) => {
    const summary = summaries[project.id]
    if (!summary) {
      navigate(`/projects/${project.id}`)
      return
    }
    if (summary.stageKey === 'create_first_chapter') {
      navigate(`/projects/${project.id}?tab=chapters&create=1`)
      return
    }
    if (!summary.chapterId) {
      navigate(`/projects/${project.id}`)
      return
    }
    if (summary.stageKey === 'edit_raw') {
      navigate(`/projects/${project.id}?tab=chapters&edit=${summary.chapterId}`)
      return
    }
    if (summary.stageKey === 'extract_shots') {
      navigate(getChapterShotsPath(project.id, summary.chapterId))
      return
    }
    if (summary.stageKey === 'prepare_shots') {
      // 先到看板看清哪些镜头还没准备好，再从看板进工作室
      navigate(getChapterBoardPath(project.id, summary.chapterId))
      return
    }
    void ensureHasShotsBeforeShooting({
      projectId: project.id,
      chapterId: summary.chapterId,
      storyboardCount: summary.storyboardCount,
      navigate,
    })
  }

  const submitForm = async (values: ProjectFormValues) => {
    if (dialogMode === 'edit' && editingProject) {
      await updateProject(editingProject.id, values)
      return
    }
    const created = await createProject(values)
    // 新建后直接进入项目，符合「创建完就要开始干活」的预期
    navigate(`/projects/${created.id}`)
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDeleteError(null)
    try {
      await removeProject(pendingDelete.id)
      setPendingDelete(null)
    } catch {
      setDeleteError('删除失败，请稍后重试')
    }
  }

  const openCreate = () => {
    setEditingProject(null)
    setDialogMode('create')
  }

  const openEdit = (project: ProjectView) => {
    setEditingProject(project)
    setDialogMode('edit')
  }

  const hasProjects = projects.length > 0
  const isEmptyResult = hasProjects && visibleProjects.length === 0

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="shrink-0 border-b border-border px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">项目</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              每个项目对应一部短剧，卡片上的「下一步」就是你现在该做的事
            </p>
          </div>
          <Button onClick={openCreate}>
            <FolderPlus className="h-4 w-4" />
            新建项目
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索项目名称或简介"
              className="pl-8 pr-8"
            />
            {search ? (
              <button
                type="button"
                aria-label="清空搜索"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm bg-transparent p-0.5 text-muted-foreground hover:text-foreground"
                onClick={() => setSearch('')}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-1">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setFilter(item.key)}
                className={cn(
                  'rounded-md bg-transparent px-2.5 py-1.5 text-xs transition-colors',
                  filter === item.key
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          <Select
            value={sortKey}
            onChange={(event) => setSortKey(event.target.value as SortKey)}
            className="ml-auto w-36"
            aria-label="排序方式"
          >
            <option value="updatedAt">最近更新</option>
            <option value="name">按名称</option>
            <option value="chapters">按章节数</option>
          </Select>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        {error ? (
          <div className="mb-4 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <div key={index} className="space-y-3 rounded-lg border border-border p-4">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            ))}
          </div>
        ) : !hasProjects ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <FolderPlus className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-medium">还没有项目</p>
              <p className="mt-1 text-xs text-muted-foreground">
                新建项目后，从粘贴剧本开始，一步步走到成片
              </p>
            </div>
            <Button onClick={openCreate}>新建第一个项目</Button>
          </div>
        ) : isEmptyResult ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <p>没有符合当前条件的项目</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearch('')
                setFilter('all')
              }}
            >
              清空筛选
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {visibleProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                summary={summaries[project.id]}
                summaryLoading={summariesLoading}
                onOpen={() => openProject(project)}
                onEdit={() => openEdit(project)}
                onDelete={() => {
                  setDeleteError(null)
                  setPendingDelete(project)
                }}
              />
            ))}
          </div>
        )}
      </div>

      <ProjectFormDialog
        open={dialogMode !== null}
        mode={dialogMode ?? 'create'}
        project={editingProject}
        styleOptions={{
          visualStyles: options.visualStyles,
          stylesByVisual: options.stylesByVisual,
          videoRatioOptions,
          defaultVideoRatio,
        }}
        onSubmit={submitForm}
        onOpenChange={(open) => {
          if (!open) setDialogMode(null)
        }}
      />

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null)
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>删除项目？</DialogTitle>
            <DialogDescription>
              「{pendingDelete?.name}」及其章节、镜头、生成记录都会被删除，且无法恢复。
            </DialogDescription>
          </DialogHeader>
          {deleteError ? (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {deleteError}
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingDelete(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default ProjectListPage
