import { useState } from 'react'
import { Button, Modal, message, Typography } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import { StudioImageTasksService } from '../../../services/generated'

/**
 * 资产参考图「一键全部生成」按钮。
 *
 * 为什么存在：`POST /api/v1/studio/image-tasks/assets/batch-image-tasks` 此前只有
 * 一个入口 —— 不可达的旧页 `ChapterPrep`，等于这个能力在 UI 上根本用不到。
 * 本组件把它变成各资产列表页（演员/角色/场景/道具/服装）上的标准按钮，五个入口
 * 共用同一套确认、提交与结果汇报逻辑，避免重复实现导致行为漂移。
 *
 * 关键行为：
 * 1. **执行前二次确认**：一次点击会给项目内该类型**全部**资产提交付费生成任务，
 *    必须让用户在提交前看到数量与影响面；
 * 2. **结果分类汇报**：`tasks`（已入队）/ `skipped`（未生成）/ `enqueue_failed`（入队失败）
 *    三类分开报，不能只报成功数 —— 否则用户会以为全部都已排队；
 * 3. **角色图的依赖提示**：角色图会引用「演员图 + 服装图」，两者没出图时角色图会在
 *    零参考图的情况下生成成功。因此 `character` 类型在确认框里明确提示先出演员/服装图。
 */

export type BatchAssetType = 'actor' | 'character' | 'scene' | 'prop' | 'costume'

type BatchAssetImageButtonProps = {
  projectId: string
  /** 资产类型：与后端 BATCH_ASSET_TYPES 一致 */
  assetType: BatchAssetType
  /** 当前列表里该类型的资产数量；仅用于确认框提示，后端始终以项目范围为准 */
  assetCount?: number
  label?: string
  buttonType?: 'default' | 'primary' | 'link' | 'text' | 'dashed'
  size?: 'small' | 'middle' | 'large'
  disabled?: boolean
  /** 提交结束（无论成功失败）后调用，通常用于刷新列表 */
  onFinished?: () => void
}

const TYPE_LABEL: Record<BatchAssetType, string> = {
  actor: '演员',
  character: '角色',
  scene: '场景',
  prop: '道具',
  costume: '服装',
}

export function BatchAssetImageButton({
  projectId,
  assetType,
  assetCount,
  label,
  buttonType = 'default',
  size = 'small',
  disabled,
  onFinished,
}: BatchAssetImageButtonProps) {
  const [running, setRunning] = useState(false)

  const submit = async () => {
    setRunning(true)
    try {
      const res = await StudioImageTasksService.createBatchAssetImageTasksApiV1StudioImageTasksAssetsBatchImageTasksPost({
        requestBody: { project_id: projectId, asset_type: assetType },
      })
      const data = (res.data ?? {}) as {
        tasks?: Array<{ asset_id?: string }>
        skipped?: Array<{ asset_id?: string; reason?: string }>
        enqueue_failed?: Array<{ asset_id?: string; reason?: string }>
      }
      const created = data.tasks?.length ?? 0
      const skipped = data.skipped ?? []
      const failed = data.enqueue_failed ?? []

      if (created > 0) {
        message.success(`已提交 ${created} 个${TYPE_LABEL[assetType]}参考图生成任务`)
      }
      // 明确区分「没提交」与「提交了但入队失败」，两者对用户意味着完全不同的下一步。
      if (skipped.length > 0) {
        const firstReason = skipped[0]?.reason ?? '未知原因'
        message.warning(`${skipped.length} 个${TYPE_LABEL[assetType]}未生成：${firstReason}`)
      }
      if (failed.length > 0) {
        message.error(`${failed.length} 个任务已创建但入队失败，请在任务中心查看后重试`)
      }
      if (created === 0 && skipped.length === 0 && failed.length === 0) {
        message.info(`项目内没有可生成的${TYPE_LABEL[assetType]}（可能尚未关联到本项目）`)
      }
    } catch (error) {
      const detail =
        (error as { body?: { detail?: string } })?.body?.detail ??
        (error instanceof Error ? error.message : '未知错误')
      message.error(`批量生成失败：${detail}`)
    } finally {
      setRunning(false)
      onFinished?.()
    }
  }

  const confirmAndSubmit = () => {
    Modal.confirm({
      title: `一键生成全部${TYPE_LABEL[assetType]}参考图？`,
      width: 520,
      okText: '开始生成',
      cancelText: '取消',
      content: (
        <div className="space-y-2">
          <div>
            将为项目内
            {typeof assetCount === 'number' ? `（当前列表 ${assetCount} 个）` : ''}
            全部{TYPE_LABEL[assetType]}各创建 1 条图片生成任务，任务会实际消耗模型额度。
          </div>
          {assetType === 'character' ? (
            <Typography.Text type="warning" className="text-xs">
              注意：角色图会引用「该角色绑定的演员图 + 服装图」。若演员/服装还没出图，
              角色图会在**零参考图**的情况下生成。建议先用「演员」「服装」页的一键生成，
              等它们出图后再生成角色图。
            </Typography.Text>
          ) : null}
          <Typography.Text type="secondary" className="text-xs">
            已生成过的资产会再次提交一条新任务（用于重跑/换角度），不会自动跳过。
          </Typography.Text>
        </div>
      ),
      onOk: submit,
    })
  }

  return (
    <Button
      type={buttonType}
      size={size}
      icon={<ThunderboltOutlined />}
      loading={running}
      disabled={disabled}
      onClick={confirmAndSubmit}
    >
      {label ?? `一键生成全部${TYPE_LABEL[assetType]}图`}
    </Button>
  )
}

export default BatchAssetImageButton
