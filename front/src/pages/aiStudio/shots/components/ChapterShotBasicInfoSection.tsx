import { Button, Input, InputNumber, Select, Tag } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import type {
  ActionBeatPhaseRead,
  CameraAngle,
  CameraMovement,
  CameraShotType,
} from '../../../../services/generated'
import {
  CAMERA_ANGLE_OPTIONS,
  CAMERA_MOVEMENT_OPTIONS,
  CAMERA_SHOT_OPTIONS,
} from '../shotOptions'

type ShotSemanticDraft = {
  camera_shot?: CameraShotType
  angle?: CameraAngle
  movement?: CameraMovement
  duration?: number
  action_beats?: Array<string>
}

type ChapterShotBasicInfoSectionProps = {
  title: string
  scriptExcerpt: string
  saving: boolean
  semanticSaving: boolean
  semantic: ShotSemanticDraft
  actionBeatPhases?: Array<ActionBeatPhaseRead>
  onTitleChange: (value: string) => void
  onScriptExcerptChange: (value: string) => void
  onSemanticChange: (patch: ShotSemanticDraft) => void
  onSave: () => void
}

export function ChapterShotBasicInfoSection({
  title,
  scriptExcerpt,
  saving,
  semanticSaving,
  semantic,
  actionBeatPhases,
  onTitleChange,
  onScriptExcerptChange,
  onSemanticChange,
  onSave,
}: ChapterShotBasicInfoSectionProps) {
  const phaseByText = new Map((actionBeatPhases ?? []).map((item) => [item.text.trim(), item.phase]))
  const phaseMeta = (phase?: ActionBeatPhaseRead['phase']) => {
    if (phase === 'trigger') return { label: '触发', color: 'gold' as const }
    if (phase === 'peak') return { label: '峰值', color: 'blue' as const }
    if (phase === 'aftermath') return { label: '收束', color: 'green' as const }
    return null
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm space-y-3">
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-900">镜头基础信息</div>
        <div className="text-[11px] text-slate-500 mt-1">先确认标题、摘录和镜头语言默认值，再继续处理系统提取结果。</div>
      </div>

      <div className="space-y-3">
        <div>
          <div className="text-xs text-gray-600 mb-1">标题</div>
          <Input
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder="标题"
          />
        </div>

        <div>
          <div className="flex items-center justify-between gap-2 mb-1">
            <div className="text-xs text-gray-600">内容 / 剧本摘录</div>
            <Button
              type="primary"
              size="small"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={onSave}
            >
              保存
            </Button>
          </div>
          <Input.TextArea
            value={scriptExcerpt}
            onChange={(e) => onScriptExcerptChange(e.target.value)}
            autoSize={{ minRows: 4, maxRows: 14 }}
            placeholder="剧本摘录"
          />
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-medium text-slate-800">镜头语言默认值</div>
              <div className="mt-1 text-[11px] text-slate-500">这里确认的是镜头语义真值，后续工作室可以微调，但仍然写回同一份分镜详情。</div>
            </div>
            <Button type="primary" size="small" loading={semanticSaving} onClick={onSave}>
              保存
            </Button>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <div className="mb-1 text-xs text-gray-600">景别</div>
              <Select
                value={semantic.camera_shot ?? undefined}
                onChange={(value) => onSemanticChange({ camera_shot: value })}
                options={CAMERA_SHOT_OPTIONS}
                placeholder="选择景别"
                className="w-full"
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-600">机位</div>
              <Select
                value={semantic.angle ?? undefined}
                onChange={(value) => onSemanticChange({ angle: value })}
                options={CAMERA_ANGLE_OPTIONS}
                placeholder="选择机位"
                className="w-full"
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-600">运镜</div>
              <Select
                value={semantic.movement ?? undefined}
                onChange={(value) => onSemanticChange({ movement: value })}
                options={CAMERA_MOVEMENT_OPTIONS}
                placeholder="选择运镜"
                className="w-full"
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-600">时长（秒）</div>
              <InputNumber
                min={1}
                max={30}
                value={semantic.duration ?? 4}
                onChange={(value) => onSemanticChange({ duration: Math.max(1, Math.round(Number(value) || 1)) })}
                className="w-full"
              />
            </div>
          </div>

          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <div className="text-xs font-medium text-slate-800">动作拍点</div>
                <div className="mt-1 text-[11px] text-slate-500">按镜头内部时间顺序保留 2-4 条即可，后续关键帧和视频会优先消费这里的已确认版本。</div>
              </div>
              <Button
                size="small"
                onClick={() => onSemanticChange({ action_beats: [...(semantic.action_beats ?? []), ''] })}
              >
                新增一条
              </Button>
            </div>
            <div className="space-y-2">
              {(semantic.action_beats ?? []).length > 0 ? (semantic.action_beats ?? []).map((item, index) => (
                <div key={`action-beat-${index}`} className="flex items-start gap-2">
                  <div className="mt-2 w-5 shrink-0 text-xs text-slate-500">{index + 1}.</div>
                  <div className="flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      {phaseMeta(phaseByText.get(item.trim())) ? (
                        <Tag color={phaseMeta(phaseByText.get(item.trim()))?.color} className="m-0">
                          {phaseMeta(phaseByText.get(item.trim()))?.label}
                        </Tag>
                      ) : null}
                    </div>
                    <Input.TextArea
                      value={item}
                      onChange={(e) => {
                        const next = [...(semantic.action_beats ?? [])]
                        next[index] = e.target.value
                        onSemanticChange({ action_beats: next })
                      }}
                      autoSize={{ minRows: 1, maxRows: 3 }}
                      placeholder="例如：听到异响后骤然僵住"
                    />
                  </div>
                  <Button
                    danger
                    size="small"
                    onClick={() => {
                      const next = [...(semantic.action_beats ?? [])]
                      next.splice(index, 1)
                      onSemanticChange({ action_beats: next })
                    }}
                  >
                    删除
                  </Button>
                </div>
              )) : (
                <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-3 text-[12px] text-slate-500">
                  当前还没有动作拍点。可以先用 AI 提取结果，再按需要补 2-4 条关键动作变化。
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
