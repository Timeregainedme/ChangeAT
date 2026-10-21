import { useState } from 'react'
import { Boxes } from 'lucide-react'
import { Button } from '../../components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog'
import { StudioShotsService } from '../../services/generated'

interface ChapterAssetCreateDialogProps {
  open: boolean
  chapterId: string
  /** 本次可能涉及的待确认资产候选数，用于确认文案。 */
  pendingAssetCount: number
  onOpenChange: (open: boolean) => void
  /** 完成后回调：页面负责刷新看板并展示结果条。 */
  onDone: (summary: { created: number; linked: number; skipped: number }) => void
}

/** 后端返回的结构只用到三个数组，这里做一次收窄，避免把 any 扩散到页面。 */
interface BatchCreateResult {
  created?: unknown[]
  linked?: unknown[]
  skipped?: unknown[]
}

/**
 * 「一键创建本章资产」。
 *
 * 与看板里的「批量确认」互补：
 *   - 批量确认处理的是「确认/忽略对白」，资产默认跳过；
 *   - 这里负责真正把资产落库（按候选建实体，同名已存在则关联而不重复创建）。
 *
 * 之所以做成章节级而不是逐镜：候选去重、角色→服装的二次绑定都需要跨镜头上下文，
 * 逐镜调用会把同名资产拆成多条。
 */
export function ChapterAssetCreateDialog({
  open,
  chapterId,
  pendingAssetCount,
  onOpenChange,
  onDone,
}: ChapterAssetCreateDialogProps) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await StudioShotsService.batchCreateAssetsFromCandidatesApiV1StudioShotsExtractedCandidatesBatchCreateAssetsPost(
        { requestBody: { chapter_id: chapterId } },
      )
      const data = (res.data ?? {}) as BatchCreateResult
      onDone({
        created: data.created?.length ?? 0,
        linked: data.linked?.length ?? 0,
        skipped: data.skipped?.length ?? 0,
      })
      onOpenChange(false)
    } catch {
      setError('创建资产失败，请稍后重试（已成功创建的资产不会回滚）')
    } finally {
      setRunning(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!running) {
          setError(null)
          onOpenChange(next)
        }
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>一键创建本章资产？</DialogTitle>
          <DialogDescription>
            会按提取候选创建或关联角色、场景、道具、服装，涉及约 {pendingAssetCount} 项。
            同名资产已存在时会关联到现有实体，不会重复创建。
          </DialogDescription>
        </DialogHeader>

        <ul className="space-y-1 text-xs text-muted-foreground">
          <li>· 创建后镜头会重新计算确认状态，缺对白的仍会留在待确认列</li>
          <li>· 角色若带服装描述，会尝试绑定项目内同名服装（已有绑定则不覆盖）</li>
        </ul>

        {error ? (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={running}>
            取消
          </Button>
          <Button onClick={run} disabled={running}>
            <Boxes className="h-3.5 w-3.5" />
            {running ? '创建中…' : '确认创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
