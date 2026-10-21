import { useMemo, useState } from 'react'
import { AlertTriangle, ClipboardCheck, ListChecks } from 'lucide-react'
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
import { cn } from '../../lib/utils'
import type { BoardShot } from './useChapterBoard'

/** 对白候选的处理方式。 */
type DialogueStrategy = 'accept' | 'ignore'
/** 资产候选的处理方式：忽略 or 跳过该镜头（留给「一键准备」建资产）。 */
type AssetStrategy = 'ignore' | 'skip'

interface ShotBatchConfirmDialogProps {
  open: boolean
  /** 已选中的镜头（只传待确认列里的）。 */
  shots: BoardShot[]
  onOpenChange: (open: boolean) => void
  /** 处理完成后回调：交给页面刷新看板，并保留失败项选中。 */
  onDone: (result: { failedIds: string[]; skippedIds: string[]; confirmedCount: number }) => void
}

interface BatchSummary {
  notExtracted: BoardShot[]
  withPendingAssets: BoardShot[]
  assetCount: number
  withPendingDialogues: BoardShot[]
  dialogueCount: number
  /** 已提取且没有待确认项，直接推进即可。 */
  clean: BoardShot[]
}

/**
 * 汇总选中镜头的确认进度。
 *
 * 分组依据是后端在列表里返回的 extraction 摘要，因此打开弹窗不需要额外请求，
 * 也不会出现「先加载再告诉你差什么」的等待。
 */
function summarize(shots: BoardShot[]): BatchSummary {
  const summary: BatchSummary = {
    notExtracted: [],
    withPendingAssets: [],
    assetCount: 0,
    withPendingDialogues: [],
    dialogueCount: 0,
    clean: [],
  }

  for (const shot of shots) {
    if (shot.extraction.state === 'not_extracted') {
      summary.notExtracted.push(shot)
      continue
    }
    const hasAssets = shot.extraction.pendingAssets > 0
    const hasDialogues = shot.extraction.pendingDialogues > 0
    if (hasAssets) {
      summary.withPendingAssets.push(shot)
      summary.assetCount += shot.extraction.pendingAssets
    }
    if (hasDialogues) {
      summary.withPendingDialogues.push(shot)
      summary.dialogueCount += shot.extraction.pendingDialogues
    }
    if (!hasAssets && !hasDialogues) summary.clean.push(shot)
  }

  return summary
}

/**
 * 批量确认向导。
 *
 * 为什么不提供「一键全部采纳」：
 * 资产候选采纳意味着**创建或关联实体**，多数场景下应该走章节级的「一键准备」，
 * 由它按类目去重后落库；在这里逐个采纳很容易制造重复资产。
 * 所以资产默认「跳过」，把含资产候选的镜头留在待确认列，并给出跳转提示。
 *
 * 对白候选是纯文本，采纳不会产生新实体，因此默认采纳。
 */
export function ShotBatchConfirmDialog({
  open,
  shots,
  onOpenChange,
  onDone,
}: ShotBatchConfirmDialogProps) {
  const [dialogueStrategy, setDialogueStrategy] = useState<DialogueStrategy>('accept')
  const [assetStrategy, setAssetStrategy] = useState<AssetStrategy>('skip')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })

  const summary = useMemo(() => summarize(shots), [shots])

  /**
   * 执行批量确认。
   *
   * 逐镜串行：一列可能有几十个镜头，每个镜头还要打 2 个查询 + N 个写请求，
   * 并发会把后端连接池打满，而且失败时无法定位到具体镜头。
   */
  const run = async () => {
    setRunning(true)
    setProgress({ done: 0, total: shots.length })

    const failedIds: string[] = []
    const skippedIds: string[] = []
    let confirmedCount = 0

    for (const shot of shots) {
      try {
        // 未提取的镜头没有任何候选可处理，状态只能是 pending，直接跳过并如实汇报
        if (shot.extraction.state === 'not_extracted') {
          skippedIds.push(shot.id)
          continue
        }

        if (shot.extraction.pendingDialogues > 0) {
          const res = await StudioShotsService.getShotExtractedDialogueCandidatesApiV1StudioShotsShotIdExtractedDialogueCandidatesGet(
            { shotId: shot.id },
          )
          const pending = (res.data ?? []).filter((item) => item.candidate_status === 'pending')
          for (const candidate of pending) {
            if (dialogueStrategy === 'accept') {
              await StudioShotsService.acceptExtractedDialogueCandidateApiV1StudioShotsExtractedDialogueCandidatesCandidateIdAcceptPatch(
                { candidateId: candidate.id },
              )
            } else {
              await StudioShotsService.ignoreExtractedDialogueCandidateApiV1StudioShotsExtractedDialogueCandidatesCandidateIdIgnorePatch(
                { candidateId: candidate.id },
              )
            }
          }
        }

        if (shot.extraction.pendingAssets > 0) {
          if (assetStrategy === 'skip') {
            // 资产没处理完，这一镜仍应留在待确认列
            skippedIds.push(shot.id)
            continue
          }
          const res = await StudioShotsService.getShotExtractedCandidatesApiV1StudioShotsShotIdExtractedCandidatesGet(
            { shotId: shot.id },
          )
          const pending = (res.data ?? []).filter((item) => item.candidate_status === 'pending')
          for (const candidate of pending) {
            await StudioShotsService.ignoreExtractedCandidateApiV1StudioShotsExtractedCandidatesCandidateIdIgnorePatch(
              { candidateId: candidate.id },
            )
          }
        }
        confirmedCount += 1
      } catch {
        failedIds.push(shot.id)
      } finally {
        setProgress((prev) => ({ ...prev, done: prev.done + 1 }))
      }
    }

    setRunning(false)
    onDone({ failedIds, skippedIds, confirmedCount })
  }

  const nothingToDo =
    summary.withPendingAssets.length === 0 &&
    summary.withPendingDialogues.length === 0 &&
    summary.clean.length === 0

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!running) onOpenChange(next)
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>批量确认 {shots.length} 个镜头</DialogTitle>
          <DialogDescription>
            确认前先看清楚每个镜头还差什么。对白是文本，采纳不产生新实体；资产候选会创建或关联实体，
            建议走章节的「一键准备」。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-[11px] text-muted-foreground">可直接推进</div>
              <div className="mt-0.5 text-lg font-semibold">{summary.clean.length}</div>
            </div>
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-[11px] text-muted-foreground">待确认对白</div>
              <div className="mt-0.5 text-lg font-semibold">
                {summary.withPendingDialogues.length}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  / {summary.dialogueCount} 条
                </span>
              </div>
            </div>
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-[11px] text-muted-foreground">待确认资产</div>
              <div className="mt-0.5 text-lg font-semibold">
                {summary.withPendingAssets.length}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  / {summary.assetCount} 项
                </span>
              </div>
            </div>
            <div className="rounded-md border border-border px-3 py-2">
              <div className="text-[11px] text-muted-foreground">未提取</div>
              <div className="mt-0.5 text-lg font-semibold">{summary.notExtracted.length}</div>
            </div>
          </div>

          {/* 对白策略 */}
          <div className="space-y-2">
            <p className="text-sm font-medium">对白候选</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {[
                { key: 'accept' as const, title: '采纳全部对白', hint: '写入镜头台词，不创建实体' },
                { key: 'ignore' as const, title: '忽略全部对白', hint: '不写入，之后仍可重新提取' },
              ].map((option) => (
                <button
                  key={option.key}
                  type="button"
                  disabled={running}
                  onClick={() => setDialogueStrategy(option.key)}
                  className={cn(
                    'rounded-md border bg-transparent px-3 py-2 text-left transition-colors',
                    dialogueStrategy === option.key
                      ? 'border-primary bg-primary/5'
                      : 'border-border hover:bg-accent',
                  )}
                >
                  <div className="text-sm font-medium">{option.title}</div>
                  <div className="text-[11px] text-muted-foreground">{option.hint}</div>
                </button>
              ))}
            </div>
          </div>

          {/* 资产策略 */}
          <div className="space-y-2">
            <p className="text-sm font-medium">资产候选</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {[
                {
                  key: 'skip' as const,
                  title: '跳过（推荐）',
                  hint: '含资产候选的镜头保持待确认，去章节「一键准备」建资产',
                },
                {
                  key: 'ignore' as const,
                  title: '忽略全部资产候选',
                  hint: '不创建实体，这些镜头会直接进入已就绪',
                },
              ].map((option) => (
                <button
                  key={option.key}
                  type="button"
                  disabled={running}
                  onClick={() => setAssetStrategy(option.key)}
                  className={cn(
                    'rounded-md border bg-transparent px-3 py-2 text-left transition-colors',
                    assetStrategy === option.key
                      ? 'border-primary bg-primary/5'
                      : 'border-border hover:bg-accent',
                  )}
                >
                  <div className="text-sm font-medium">{option.title}</div>
                  <div className="text-[11px] text-muted-foreground">{option.hint}</div>
                </button>
              ))}
            </div>
          </div>

          {summary.notExtracted.length > 0 ? (
            <div className="flex items-start gap-2 rounded-md bg-state-pending/10 px-3 py-2 text-xs text-state-pending">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                有 {summary.notExtracted.length} 个镜头还没做过信息提取，本次会跳过它们。
                可以先去提取，或在侧滑里标记「无需提取」。
              </span>
            </div>
          ) : null}

          {running ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ClipboardCheck className="h-3.5 w-3.5" />
              正在处理 {progress.done} / {progress.total} 个镜头…
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={running}>
            取消
          </Button>
          <Button onClick={run} disabled={running || nothingToDo}>
            <ListChecks className="h-3.5 w-3.5" />
            {running ? '处理中…' : '开始确认'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
