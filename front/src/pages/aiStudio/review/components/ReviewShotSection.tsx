/**
 * 检查流程 · 第二段「分镜」。
 *
 * 目标：逐镜头核对「时长 / 景别 / 角度 / 运镜 / 场景」这些直接影响出片的字段，
 * 允许就地修改并立即保存，避免为了改一个时长反复跳转到分镜编辑页。
 *
 * 行为边界：
 * - 只改这几个「生成参数」字段；标题、剧本片段、动作节拍等仍归分镜编辑页。
 * - 保存走 `PATCH /studio/shot-details/{shot_id}`，保存成功后把最新 detail 回传给父级，
 *   保证同一页面里后续段落读到的是最新值。
 */
import { useState } from 'react'
import { Button, Card, Empty, InputNumber, Select, Space, Tag, Tooltip, Typography, message } from 'antd'
import { EditOutlined, PictureOutlined } from '@ant-design/icons'
import { StudioShotDetailsService } from '../../../../services/generated'
import type { ShotDetailRead, ShotDetailUpdate } from '../../../../services/generated'
import { CAMERA_ANGLE_OPTIONS, CAMERA_MOVEMENT_OPTIONS, CAMERA_SHOT_OPTIONS } from '../../shots/shotOptions'
import { resolveAssetUrl } from '../../assets/utils'
import type { ShotBundle } from '../types'

const { Text } = Typography

type ReviewShotSectionProps = {
  bundles: ShotBundle[]
  /** 本章可选的场景（来自第一段的资产清单） */
  sceneOptions: Array<{ value: string; label: string }>
  onUpdated: (shotId: string, detail: ShotDetailRead) => void
  onOpenShot: (shotId: string) => void
}

export function ReviewShotSection({
  bundles,
  sceneOptions,
  onUpdated,
  onOpenShot,
}: ReviewShotSectionProps) {
  return (
    <div className="space-y-3">
      {bundles.length === 0 ? (
        <Empty description="本章还没有分镜" />
      ) : (
        bundles.map((bundle) => (
          <ShotRow
            key={bundle.shot.id}
            bundle={bundle}
            sceneOptions={sceneOptions}
            onUpdated={onUpdated}
            onOpenShot={onOpenShot}
          />
        ))
      )}
    </div>
  )
}

/**
 * 单个镜头的分镜字段行。
 *
 * 内部维护一份 draft：输入过程中不打扰用户，失焦/确认后才提交，
 * 避免每敲一个数字就发一次请求。
 */
function ShotRow({
  bundle,
  sceneOptions,
  onUpdated,
  onOpenShot,
}: {
  bundle: ShotBundle
  sceneOptions: Array<{ value: string; label: string }>
  onUpdated: (shotId: string, detail: ShotDetailRead) => void
  onOpenShot: (shotId: string) => void
}) {
  const { shot, detail, prep } = bundle
  const [draft, setDraft] = useState<ShotDetailUpdate>(() => ({
    duration: detail?.duration ?? 0,
    camera_shot: detail?.camera_shot,
    angle: detail?.angle,
    movement: detail?.movement,
    scene_id: detail?.scene_id ?? null,
  }))
  const [saving, setSaving] = useState(false)

  const thumbnailUrl = resolveAssetUrl(shot.thumbnail)
  const lineCount = prep?.saved_dialogue_lines?.length ?? 0
  const lineReady = lineCount === 0 || (prep?.saved_dialogue_lines ?? []).every((l) => l.text?.trim())
  const basicReady = Boolean(draft.camera_shot && draft.angle && draft.movement && (draft.duration ?? 0) > 0)

  /** 提交单个字段的修改（只发 patch 的那一个键，减少误覆盖）。 */
  const saveField = async (patch: ShotDetailUpdate) => {
    if (!detail) {
      message.warning('该镜头还没有分镜详情，请先到分镜编辑页保存基础信息')
      return
    }
    setSaving(true)
    try {
      const resp = await StudioShotDetailsService.updateShotDetailApiV1StudioShotDetailsShotIdPatch({
        shotId: shot.id,
        requestBody: patch,
      })
      const next = (resp.data ?? null) as ShotDetailRead | null
      if (next) onUpdated(shot.id, next)
      message.success('已保存')
    } catch (error) {
      message.error(error instanceof Error ? `保存失败：${error.message}` : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      size="small"
      title={
        <Space size={8} wrap>
          <Tag color="blue">#{shot.index + 1}</Tag>
          <span className="font-medium">{shot.title || '未命名镜头'}</span>
          <Tag color={shot.status === 'ready' ? 'green' : 'orange'}>
            {shot.status === 'ready' ? '信息已确认' : '待确认'}
          </Tag>
          <Tag color={lineReady ? 'green' : 'red'}>台词 {lineCount}</Tag>
          <Tag color={basicReady ? 'green' : 'orange'}>
            {basicReady ? '分镜字段完整' : '分镜字段待补'}
          </Tag>
        </Space>
      }
      extra={
        <Button size="small" icon={<EditOutlined />} onClick={() => onOpenShot(shot.id)}>
          编辑镜头
        </Button>
      }
    >
      <div className="flex gap-3">
        <div className="w-20 h-20 shrink-0 rounded overflow-hidden bg-gray-50 flex items-center justify-center">
          {thumbnailUrl ? (
            <img src={thumbnailUrl} alt={shot.title} className="w-full h-full object-cover" loading="lazy" />
          ) : (
            <PictureOutlined className="text-gray-300" style={{ fontSize: 20 }} />
          )}
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Tooltip title="镜头时长（秒），影响视频生成时长">
              <InputNumber
                size="small"
                min={1}
                max={15}
                addonBefore="时长"
                addonAfter="秒"
                value={draft.duration ?? 0}
                disabled={saving || !detail}
                onChange={(val) => setDraft((prev) => ({ ...prev, duration: val ?? 0 }))}
                onBlur={() => {
                  if ((draft.duration ?? 0) !== (detail?.duration ?? 0)) {
                    void saveField({ duration: draft.duration ?? 0 })
                  }
                }}
                style={{ width: 130 }}
              />
            </Tooltip>

            <Select
              size="small"
              placeholder="景别"
              value={draft.camera_shot}
              disabled={saving || !detail}
              options={CAMERA_SHOT_OPTIONS}
              style={{ width: 110 }}
              onChange={(val) => {
                setDraft((prev) => ({ ...prev, camera_shot: val }))
                void saveField({ camera_shot: val })
              }}
            />
            <Select
              size="small"
              placeholder="角度"
              value={draft.angle}
              disabled={saving || !detail}
              options={CAMERA_ANGLE_OPTIONS}
              style={{ width: 110 }}
              onChange={(val) => {
                setDraft((prev) => ({ ...prev, angle: val }))
                void saveField({ angle: val })
              }}
            />
            <Select
              size="small"
              placeholder="运镜"
              value={draft.movement}
              disabled={saving || !detail}
              options={CAMERA_MOVEMENT_OPTIONS}
              style={{ width: 120 }}
              onChange={(val) => {
                setDraft((prev) => ({ ...prev, movement: val }))
                void saveField({ movement: val })
              }}
            />
            <Select
              size="small"
              placeholder="场景"
              allowClear
              showSearch
              optionFilterProp="label"
              value={draft.scene_id ?? undefined}
              disabled={saving || !detail}
              options={sceneOptions}
              style={{ width: 160 }}
              onChange={(val) => {
                const nextScene = (val ?? null) as string | null
                setDraft((prev) => ({ ...prev, scene_id: nextScene }))
                void saveField({ scene_id: nextScene })
              }}
            />
          </div>

          <div className="text-xs text-gray-500 truncate">
            {shot.script_excerpt || '（无剧本片段）'}
          </div>
          {!detail ? (
            <Text type="danger" className="text-xs">
              缺少分镜详情记录，需先在分镜编辑页保存一次基础信息。
            </Text>
          ) : null}
        </div>
      </div>
    </Card>
  )
}
