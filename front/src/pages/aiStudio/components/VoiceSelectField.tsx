import { useCallback, useEffect, useMemo, useState } from 'react'
import { Select, Tag, Typography } from 'antd'
import { StudioAudioTasksService } from '../../../services/generated'
import type { VoiceItem } from '../../../services/generated'

/**
 * 音色选择控件（角色 / 演员 / 音色管理页三处复用）。
 *
 * 为什么存在：
 * 1. 角色与演员都需要「绑一个供应商音色」，控件行为必须完全一致，否则同一份数据在
 *    两个入口会呈现出不同的候选集合；
 * 2. 供应商音色列表是**运行时**通过 `GET /api/v1/studio/audio-tasks/voices` 拉取的，
 *    且当前只有 `compshare_model_api` 提供该接口 —— 其他供应商会返回 400。控件必须
 *    在这种「拿不到列表」的情况下仍然可用：至少能把**已保存的 voice_id** 显示出来，
 *    不能让用户看到一个空白框而误以为自己没配过音色。
 *
 * 交互约定：
 * - `value` 为供应商侧 `voice_id`，空字符串/null 表示未绑定；
 * - 选择时通过 `onChange` 回传 `voice_id` 与 `voice_source`（preset / custom），
 *   调用方直接写库即可；
 * - 已保存但不在候选列表里的音色会被补进选项（标注「已保存」），因此清空动作是
 *   唯一会真正丢掉 voice_id 的路径。
 */

export type VoiceSource = 'preset' | 'custom'

export type VoiceChoice = {
  voice_id: string | null
  voice_source: VoiceSource | null
}

type VoiceSelectFieldProps = {
  /** 当前绑定的供应商音色 ID（受控） */
  value?: string | null
  /** 选择结果回调：同时回传音色 ID 与来源 */
  onChange?: (next: VoiceChoice) => void
  /** 音频模型 ID；不传则后端使用默认音频模型 */
  modelId?: string | null
  /** 音色类型：preset（预置）或 custom（自定义复刻） */
  kind?: VoiceSource
  placeholder?: string
  disabled?: boolean
  allowClear?: boolean
}

/** 已保存但不在供应商列表中的音色所用的选项值前缀，避免与真实 voice_id 冲突。 */
const SAVED_OPTION_PREFIX = '__saved__:'

export function VoiceSelectField({
  value,
  onChange,
  modelId,
  kind = 'preset',
  placeholder = '选择音色（可搜索）',
  disabled,
  allowClear = true,
}: VoiceSelectFieldProps) {
  const [voices, setVoices] = useState<VoiceItem[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const loadVoices = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await StudioAudioTasksService.listAudioVoicesApiV1StudioAudioTasksVoicesGet({
        modelId: modelId ?? null,
        kind,
      })
      setVoices(res.data ?? [])
    } catch (error) {
      // 供应商不支持音色列表（例如非 compshare 供应商）属于预期情况，
      // 这里只降级为「仅显示已保存音色」，不阻断表单。
      setVoices([])
      setLoadError(error instanceof Error ? error.message : '音色列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [kind, modelId])

  useEffect(() => {
    void loadVoices()
  }, [loadVoices])

  const trimmedValue = (value ?? '').trim()

  const options = useMemo(() => {
    const fromProvider = voices
      .map((v) => ({
        value: v.voice_id ?? '',
        // 语种后缀帮助用户在几十个音色里快速判断（供应商常给 zh/en 混合列表）
        label: v.language ? `${v.name ?? v.voice_id}（${v.language}）` : (v.name ?? v.voice_id ?? ''),
      }))
      .filter((o) => Boolean(o.value))

    // 已保存的音色若不在供应商当前列表里（换了模型、供应商下线了该音色等），
    // 单独补一条只读选项，保证用户看得见、且不会因为「看不见」而被误清空。
    if (trimmedValue && !fromProvider.some((o) => o.value === trimmedValue)) {
      fromProvider.unshift({
        value: `${SAVED_OPTION_PREFIX}${trimmedValue}`,
        label: `已保存：${trimmedValue}`,
      })
    }
    return fromProvider
  }, [trimmedValue, voices])

  return (
    <div className="space-y-1">
      <Select
        className="w-full"
        placeholder={placeholder}
        loading={loading}
        disabled={disabled}
        allowClear={allowClear}
        showSearch
        optionFilterProp="label"
        filterOption={(input, option) =>
          String(option?.label ?? '')
            .toLowerCase()
            .includes(input.toLowerCase())
        }
        value={trimmedValue ? (voices.some((v) => v.voice_id === trimmedValue) ? trimmedValue : `${SAVED_OPTION_PREFIX}${trimmedValue}`) : undefined}
        options={options}
        onChange={(next) => {
          if (!next) {
            onChange?.({ voice_id: null, voice_source: null })
            return
          }
          const raw = String(next)
          if (raw.startsWith(SAVED_OPTION_PREFIX)) {
            // 重新选中原来那条已保存音色：保持原值，不改变来源语义。
            onChange?.({ voice_id: raw.slice(SAVED_OPTION_PREFIX.length), voice_source: trimmedValue === value ? null : kind })
            return
          }
          onChange?.({ voice_id: raw, voice_source: kind })
        }}
      />
      {loadError ? (
        <Typography.Text type="secondary" className="text-xs">
          音色列表不可用（{loadError}）；当前仅显示已保存的音色，可直接清空或稍后重试。
        </Typography.Text>
      ) : null}
      {!loadError && !loading && voices.length === 0 ? (
        <Typography.Text type="secondary" className="text-xs">
          供应商未返回任何音色。请到「模型管理」确认默认音频模型所属供应商支持音色列表（当前仅优云智算支持）。
        </Typography.Text>
      ) : null}
      {trimmedValue ? (
        <div>
          <Tag color="blue">当前：{trimmedValue}</Tag>
        </div>
      ) : null}
    </div>
  )
}

export default VoiceSelectField
