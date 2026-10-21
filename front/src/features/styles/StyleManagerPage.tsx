import { useCallback, useEffect, useMemo, useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { Textarea } from '../../components/ui/textarea'
import { Badge } from '../../components/ui/badge'
import { StudioStylesService } from '../../services/generated'
import { invalidateProjectStyleOptionsCache } from '../../pages/aiStudio/project/useProjectStyleOptions'
import type { ProjectStyleOptionRead } from '../../services/generated'

/** 画面表现形式：与后端目录里的取值保持一致（现实 / 动漫）。 */
const DEFAULT_VISUAL_STYLES = ['现实', '动漫']

interface StyleFormState {
  visualStyle: string
  name: string
  description: string
  /** 提示词质感描述：留空则回落到内置风格包 */
  promptPack: string
}

const EMPTY_FORM: StyleFormState = {
  visualStyle: '现实',
  name: '',
  description: '',
  promptPack: '',
}

/**
 * 风格管理页。
 *
 * 风格原来是后端枚举（真人都市 / 动漫3D / 水墨画 …），加一个新风格要改代码发版。
 * 现在目录落在 `project_styles` 表里，这一页就是它的维护入口：
 *   - 按「画面表现形式」分组展示，组内可排序（新建默认排到末尾）；
 *   - 新增时只需要三个字段：表现形式、风格名称、说明（参考原有风格的写法）；
 *   - 删除只影响「以后新建项目时是否可选」，已建项目的历史值不会丢。
 */
export function StyleManagerPage() {
  const [styles, setStyles] = useState<ProjectStyleOptionRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<ProjectStyleOptionRead | null>(null)
  const [form, setForm] = useState<StyleFormState>(EMPTY_FORM)
  const [pendingDelete, setPendingDelete] = useState<ProjectStyleOptionRead | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await StudioStylesService.listStylesApiV1StudioStylesGet()
      setStyles((res.data ?? []) as ProjectStyleOptionRead[])
    } catch {
      setStyles([])
      setError('风格目录加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** 按表现形式分组，保持后端返回的顺序（现实在前、动漫在后）。 */
  const grouped = useMemo(() => {
    const map = new Map<string, ProjectStyleOptionRead[]>()
    styles.forEach((item) => {
      const list = map.get(item.visual_style) ?? []
      list.push(item)
      map.set(item.visual_style, list)
    })
    return Array.from(map.entries())
  }, [styles])

  const visualStyleOptions = useMemo(() => {
    const seen = new Set<string>(DEFAULT_VISUAL_STYLES)
    styles.forEach((item) => seen.add(item.visual_style))
    return Array.from(seen)
  }, [styles])

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setDialogOpen(true)
  }

  const openEdit = (item: ProjectStyleOptionRead) => {
    setEditing(item)
    setForm({
      visualStyle: item.visual_style,
      name: item.name,
      description: item.description ?? '',
      promptPack: item.prompt_pack ?? '',
    })
    setFormError(null)
    setDialogOpen(true)
  }

  /** 提交新增 / 修改。失败原因（例如同组重名）直接展示在弹窗里。 */
  const submit = async () => {
    if (!form.name.trim()) {
      setFormError('请填写风格名称')
      return
    }
    setSaving(true)
    setFormError(null)
    try {
      if (editing) {
        await StudioStylesService.updateStyleApiV1StudioStylesStyleIdPatch({
          styleId: editing.id,
          requestBody: {
            name: form.name.trim(),
            description: form.description.trim(),
            prompt_pack: form.promptPack.trim(),
          },
        })
      } else {
        await StudioStylesService.createStyleApiV1StudioStylesPost({
          requestBody: {
            visual_style: form.visualStyle,
            name: form.name.trim(),
            description: form.description.trim(),
            prompt_pack: form.promptPack.trim(),
          },
        })
      }
      // 让新建项目弹窗下次打开时重新拉取目录，而不是用旧缓存
      invalidateProjectStyleOptionsCache()
      setDialogOpen(false)
      await load()
    } catch (err) {
      const detail = (err as { body?: { detail?: string } })?.body?.detail
      setFormError(detail || '保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    try {
      await StudioStylesService.deleteStyleApiV1StudioStylesStyleIdDelete({ styleId: pendingDelete.id })
      invalidateProjectStyleOptionsCache()
      setPendingDelete(null)
      await load()
    } catch {
      setError('删除失败，请稍后重试')
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="shrink-0 border-b border-border px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">风格管理</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              项目创建时可选的「画面表现形式 + 风格」由这里维护；删除只影响以后新建项目
            </p>
          </div>
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" />
            新增风格
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        {error ? (
          <div className="mb-4 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="space-y-4">
            {[0, 1].map((group) => (
              <div key={group} className="space-y-2 rounded-lg border border-border p-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-16 w-full" />
              </div>
            ))}
          </div>
        ) : grouped.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <p>还没有任何风格</p>
            <Button size="sm" onClick={openCreate}>
              新增第一个风格
            </Button>
          </div>
        ) : (
          <div className="space-y-5">
            {grouped.map(([visualStyle, items]) => (
              <section key={visualStyle} className="space-y-3">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold">{visualStyle}</h2>
                  <Badge variant="secondary">{items.length}</Badge>
                </div>

                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {items.map((item) => (
                    <Card key={item.id} className="flex flex-col p-4">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{item.name}</p>
                          <p className="mt-1 line-clamp-2 min-h-[2rem] text-xs text-muted-foreground">
                            {item.description || '暂无说明'}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="编辑风格"
                            onClick={() => openEdit(item)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="删除风格"
                            className="text-muted-foreground hover:text-destructive"
                            onClick={() => setPendingDelete(item)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        排序 {item.sort_order} · ID {item.id}
                      </p>
                    </Card>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑风格' : '新增风格'}</DialogTitle>
            <DialogDescription>
              名称会直接出现在新建项目的「剧集风格」下拉里，建议与已有风格保持同一粒度。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="style-visual">画面表现形式</Label>
              <Select
                id="style-visual"
                value={form.visualStyle}
                disabled={Boolean(editing)}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, visualStyle: event.target.value }))
                }
              >
                {visualStyleOptions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
              {editing ? (
                <p className="text-[11px] text-muted-foreground">
                  表现形式决定风格归到哪一组，创建后不可改，避免已有项目引用错位
                </p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="style-name">风格名称</Label>
              <Input
                id="style-name"
                placeholder="例如：赛博国风"
                value={form.name}
                onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="style-desc">说明</Label>
              <Textarea
                id="style-desc"
                rows={3}
                placeholder="一句话描述画面质感，例如：霓虹与水墨叠加，冷紫主调，粒子与飞白结合"
                value={form.description}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, description: event.target.value }))
                }
              />
              <p className="text-[11px] text-muted-foreground">
                参考已有风格：只写画面可观察的要素（光线、材质、色调），不要写抽象评价词
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="style-pack">提示词质感描述</Label>
              <Textarea
                id="style-pack"
                rows={3}
                placeholder="例如：霓虹与水墨叠加，冷紫主调，粒子特效与飞白笔触并存"
                value={form.promptPack}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, promptPack: event.target.value }))
                }
              />
              <p className="text-[11px] text-muted-foreground">
                生成资产图/角色图时会拼进提示词，决定实际画风。留空则使用内置的「真人都市」质感描述。
              </p>
            </div>

            {formError ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {formError}
              </p>
            ) : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button onClick={submit} disabled={saving}>
              {saving ? '保存中…' : editing ? '保存修改' : '创建风格'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingDelete !== null} onOpenChange={(open) => (open ? null : setPendingDelete(null))}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>删除风格「{pendingDelete?.name}」？</DialogTitle>
            <DialogDescription>
              删除后新建项目不再出现该选项；已有项目里的这个风格值不会被修改。
            </DialogDescription>
          </DialogHeader>
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

export default StyleManagerPage
