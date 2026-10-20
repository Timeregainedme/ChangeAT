import { useEffect, useState } from 'react'
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
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Switch } from '../../components/ui/switch'
import { Textarea } from '../../components/ui/textarea'
import type { ProjectFormValues } from './useProjectList'
import type { ProjectView } from './types'

interface StyleOption {
  value: string
  label: string
}

export interface ProjectStyleOptionsInput {
  visualStyles: StyleOption[]
  stylesByVisual: Record<string, StyleOption[]>
  videoRatioOptions: StyleOption[]
  defaultVideoRatio: string
}

interface ProjectFormDialogProps {
  open: boolean
  mode: 'create' | 'edit'
  /** 编辑模式下回填的项目；创建模式传 null。 */
  project: ProjectView | null
  styleOptions: ProjectStyleOptionsInput
  /** 提交失败时把错误显示在弹窗内，避免用户以为已经保存。 */
  onSubmit: (values: ProjectFormValues) => Promise<void>
  onOpenChange: (open: boolean) => void
}

/** 表单的空白初值，创建模式每次打开都重置到这里。 */
function emptyValues(styleOptions: ProjectStyleOptionsInput): ProjectFormValues {
  const visual = styleOptions.visualStyles[0]?.value ?? '现实'
  const style =
    styleOptions.stylesByVisual[visual]?.[0]?.value ?? styleOptions.visualStyles[0]?.value ?? ''
  return {
    name: '',
    description: '',
    visualStyle: visual,
    style,
    seed: Math.floor(Math.random() * 99999),
    unifyStyle: true,
    defaultVideoRatio: styleOptions.defaultVideoRatio || null,
  }
}

/**
 * 项目创建 / 编辑弹窗。
 *
 * 创建与编辑共用一个表单：字段完全一致，分开写两份必然会漏字段或校验不一致。
 * 画面风格变化时自动把剧集风格切到该风格的默认值，避免出现「动漫 + 真人都市」的组合。
 */
export function ProjectFormDialog({
  open,
  mode,
  project,
  styleOptions,
  onSubmit,
  onOpenChange,
}: ProjectFormDialogProps) {
  const [values, setValues] = useState<ProjectFormValues>(() => emptyValues(styleOptions))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 每次打开时重置：创建模式给空白值，编辑模式回填当前项目
  useEffect(() => {
    if (!open) return
    setError(null)
    if (mode === 'edit' && project) {
      setValues({
        name: project.name,
        description: project.description,
        visualStyle: project.visualStyle,
        style: project.style,
        seed: project.seed,
        unifyStyle: project.unifyStyle,
        defaultVideoRatio: project.defaultVideoRatio,
      })
    } else {
      setValues(emptyValues(styleOptions))
    }
  }, [open, mode, project, styleOptions])

  const styleChoices = styleOptions.stylesByVisual[values.visualStyle] ?? []

  /** 切换画面风格时同步剧集风格，保证两者始终是合法组合。 */
  const changeVisualStyle = (visual: string) => {
    const nextStyle = styleOptions.stylesByVisual[visual]?.[0]?.value ?? ''
    setValues((prev) => ({ ...prev, visualStyle: visual, style: nextStyle }))
  }

  const submit = async () => {
    if (!values.name.trim()) {
      setError('请填写项目名称')
      return
    }
    if (!values.style) {
      setError('请选择剧集风格')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      await onSubmit({ ...values, name: values.name.trim(), description: values.description.trim() })
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{mode === 'edit' ? '编辑项目' : '新建项目'}</DialogTitle>
          <DialogDescription>
            画面风格与剧集风格决定后续生成资产的默认走向，创建后仍可修改。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-name">项目名称</Label>
            <Input
              id="project-name"
              placeholder="例如：雨夜长安"
              value={values.name}
              onChange={(event) => setValues((prev) => ({ ...prev, name: event.target.value }))}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="project-description">简介</Label>
            <Textarea
              id="project-description"
              placeholder="一句话说明这个故事讲什么，方便团队其他人快速理解"
              value={values.description}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, description: event.target.value }))
              }
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="project-visual-style">画面风格</Label>
              <Select
                id="project-visual-style"
                value={values.visualStyle}
                onChange={(event) => changeVisualStyle(event.target.value)}
              >
                {styleOptions.visualStyles.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="project-style">剧集风格</Label>
              <Select
                id="project-style"
                value={values.style}
                onChange={(event) => setValues((prev) => ({ ...prev, style: event.target.value }))}
              >
                {styleChoices.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="project-seed">种子</Label>
              <Input
                id="project-seed"
                type="number"
                value={values.seed}
                onChange={(event) =>
                  setValues((prev) => ({ ...prev, seed: Number(event.target.value) || 0 }))
                }
              />
              <p className="text-[11px] text-muted-foreground">
                同一项目内固定种子，画面风格更稳定
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="project-ratio">画幅比例</Label>
              <Select
                id="project-ratio"
                value={values.defaultVideoRatio ?? ''}
                onChange={(event) =>
                  setValues((prev) => ({ ...prev, defaultVideoRatio: event.target.value || null }))
                }
              >
                <option value="">使用系统默认</option>
                {styleOptions.videoRatioOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="flex items-center justify-between rounded-md border border-border px-3 py-2.5">
            <div>
              <p className="text-sm font-medium">统一画面风格</p>
              <p className="text-[11px] text-muted-foreground">
                开启后，后续生成会尽量沿用同一套视觉风格
              </p>
            </div>
            <Switch
              checked={values.unifyStyle}
              onCheckedChange={(checked) => setValues((prev) => ({ ...prev, unifyStyle: checked }))}
            />
          </div>

          {error ? (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={submit} disabled={submitting}>
            {submitting ? '保存中…' : mode === 'edit' ? '保存修改' : '创建项目'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
