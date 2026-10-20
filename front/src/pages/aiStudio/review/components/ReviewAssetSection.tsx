/**
 * 检查流程 · 第一段「参考图」。
 *
 * 目标：一屏看清本章所有镜头用到的角色/服装/场景/道具，
 * 哪一张已有参考图、哪一张还缺图、哪一条候选还没确认。
 *
 * 行为边界：
 * - 这里只做「检查 + 补图（重抽）」与跳转，不承担资产名称/描述的编辑
 *   （编辑属于资产页/角色页的职责，避免检查页演化成第二个资产编辑器）。
 * - 出图按钮走 `batch-image-tasks`，只提交当前这一个资产，语义是「重新生成参考图」。
 */
import { useMemo, useState } from 'react'
import { Alert, Button, Card, Empty, Space, Tag, Tooltip, Typography, message } from 'antd'
import { PictureOutlined, ReloadOutlined } from '@ant-design/icons'
import { StudioImageTasksService } from '../../../../services/generated'
import { resolveAssetUrl } from '../../assets/utils'
import type { ReviewAssetRow, ReviewAssetType, ReviewPendingCandidate } from '../types'

const { Text } = Typography

const TYPE_ORDER: ReviewAssetType[] = ['character', 'costume', 'scene', 'prop']
const TYPE_LABEL: Record<ReviewAssetType, string> = {
  character: '角色',
  costume: '服装',
  scene: '场景',
  prop: '道具',
}

type ReviewAssetSectionProps = {
  projectId: string
  assets: ReviewAssetRow[]
  pendingCandidates: ReviewPendingCandidate[]
  /** 补图/重抽后通知父级重新拉取数据 */
  onChanged: () => void
  /** 跳到资产维护位置（角色在项目角色页，其余在资产页） */
  onOpenAsset: (type: ReviewAssetType, entityId: string) => void
  /** 跳到镜头编辑页（用于处理待确认候选） */
  onOpenShot: (shotId: string) => void
}

export function ReviewAssetSection({
  projectId,
  assets,
  pendingCandidates,
  onChanged,
  onOpenAsset,
  onOpenShot,
}: ReviewAssetSectionProps) {
  /** 每个资产独立 loading，避免一次补图把所有按钮都锁住。 */
  const [busyKeys, setBusyKeys] = useState<Record<string, boolean>>({})

  const grouped = useMemo(() => {
    const map = new Map<ReviewAssetType, ReviewAssetRow[]>()
    for (const type of TYPE_ORDER) map.set(type, [])
    for (const row of assets) map.get(row.type)?.push(row)
    return map
  }, [assets])

  const readyCount = assets.filter((row) => Boolean(row.thumbnail)).length

  /**
   * 重新生成单个资产的参考图。
   *
   * 说明：`batch-image-tasks` 的语义是「按资产重建图片任务」，不检查已有 file_id，
   * 因此这里显式提示是「重抽」，避免用户误以为是免费补齐。
   */
  const regenerateImage = async (row: ReviewAssetRow) => {
    if (busyKeys[row.key]) return
    setBusyKeys((prev) => ({ ...prev, [row.key]: true }))
    try {
      const resp =
        await StudioImageTasksService.createBatchAssetImageTasksApiV1StudioImageTasksAssetsBatchImageTasksPost({
          requestBody: {
            project_id: projectId,
            asset_type: row.type,
            asset_ids: [row.entityId],
          },
        })
      const data = resp.data as
        | { tasks?: unknown[]; skipped?: unknown[]; enqueue_failed?: unknown[] }
        | undefined
      const queued = data?.tasks?.length ?? 0
      const skipped = data?.skipped?.length ?? 0
      const failed = data?.enqueue_failed?.length ?? 0
      if (queued > 0) {
        message.success(`「${row.name}」已提交出图（队列 ${queued}，跳过 ${skipped}，失败 ${failed}）`)
      } else {
        message.warning(`「${row.name}」未提交任何出图任务（跳过 ${skipped}，失败 ${failed}）`)
      }
      onChanged()
    } catch (error) {
      message.error(error instanceof Error ? `出图失败：${error.message}` : '出图失败')
    } finally {
      setBusyKeys((prev) => ({ ...prev, [row.key]: false }))
    }
  }

  return (
    <div className="space-y-4">
      <Card size="small">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Space size={8} wrap>
            <Tag color={readyCount === assets.length ? 'green' : 'orange'}>
              已出图 {readyCount} / {assets.length}
            </Tag>
            {pendingCandidates.length > 0 ? (
              <Tag color="red">待确认候选 {pendingCandidates.length}</Tag>
            ) : (
              <Tag color="green">候选已处理完</Tag>
            )}
          </Space>
          <Text type="secondary" className="text-xs">
            本章镜头引用到的资产都会列在这里；缺图的可以先补图，再进入「分镜」段。
          </Text>
        </div>
      </Card>

      {pendingCandidates.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          message="有提取候选尚未确认"
          description={
            <div className="space-y-1">
              <div className="text-xs">
                这些候选还没决定「关联到已有资产」还是「忽略」，会直接影响出图与视频参考图的完整性。
              </div>
              <Space wrap size={6}>
                {pendingCandidates.map((item) => (
                  <Tag
                    key={item.key}
                    color="orange"
                    style={{ cursor: 'pointer' }}
                    onClick={() => onOpenShot(item.shotId)}
                  >
                    {item.shotLabel} · {TYPE_LABEL[item.type]}「{item.name}」→ 去确认
                  </Tag>
                ))}
              </Space>
            </div>
          }
        />
      ) : null}

      {assets.length === 0 && pendingCandidates.length === 0 ? (
        <Empty description="本章还没有可检查的资产，请先在分镜编辑页完成提取" />
      ) : null}

      {TYPE_ORDER.map((type) => {
        const rows = grouped.get(type) ?? []
        if (rows.length === 0) return null
        return (
          <Card key={type} size="small" title={`${TYPE_LABEL[type]}（${rows.length}）`}>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {rows.map((row) => {
                const imageUrl = resolveAssetUrl(row.thumbnail)
                return (
                  <div key={row.key} className="border rounded-md overflow-hidden bg-white">
                    <div className="relative aspect-square bg-gray-50 flex items-center justify-center">
                      {imageUrl ? (
                        <img
                          src={imageUrl}
                          alt={row.name}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div className="text-center text-gray-400">
                          <PictureOutlined style={{ fontSize: 22 }} />
                          <div className="text-xs mt-1">未出图</div>
                        </div>
                      )}
                      <Tag
                        color={imageUrl ? 'green' : 'orange'}
                        className="!absolute top-1 right-1 !m-0"
                      >
                        {imageUrl ? '有图' : '缺图'}
                      </Tag>
                    </div>
                    <div className="p-2 space-y-1">
                      <Tooltip title={row.name}>
                        <div className="text-xs font-medium truncate">{row.name}</div>
                      </Tooltip>
                      <div className="text-[11px] text-gray-500 truncate">
                        出现于 {row.shotLabels.join('、') || '—'}
                      </div>
                      <Space size={4} wrap>
                        <Button
                          size="small"
                          type="link"
                          icon={<PictureOutlined />}
                          onClick={() => onOpenAsset(row.type, row.entityId)}
                        >
                          打开
                        </Button>
                        <Button
                          size="small"
                          type="link"
                          icon={<ReloadOutlined />}
                          loading={!!busyKeys[row.key]}
                          onClick={() => void regenerateImage(row)}
                        >
                          {imageUrl ? '重抽' : '出图'}
                        </Button>
                      </Space>
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        )
      })}
    </div>
  )
}
