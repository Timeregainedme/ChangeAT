import { useEffect, useState } from 'react'
import { Input, InputNumber, Modal, Select, Typography, message } from 'antd'
import { StudioEntitiesApi } from '../../../../services/studioEntities'
import { ProjectVisualStyleAndStyleFields } from '../../project/ProjectVisualStyleAndStyleFields'
import { useProjectStyleOptions } from '../../project/useProjectStyleOptions'
import { VoiceSelectField, type VoiceSource } from '../../components/VoiceSelectField'

export type ActorEntityLike = {
  id: string
  name: string
  description?: string | null
  tags?: string[]
  view_count?: number | null
  visual_style?: string
  style?: string
  /** 演员默认音色。角色未配音色时 TTS 会回退到它（见 `_resolve_audio_voice`） */
  voice_id?: string | null
  voice_source?: string | null
  voice_description?: string | null
}

function normalizeTags(input: string): string[] {
  return input
    .split(/[,，\n]/g)
    .map((t) => t.trim())
    .filter(Boolean)
}

export function ActorEntityFormModal({
  open,
  editing,
  linkProjectId,
  linkChapterId,
  linkShotId,
  onCancel,
  onSuccess,
}: {
  open: boolean
  editing: ActorEntityLike | null
  linkProjectId?: string
  linkChapterId?: string
  linkShotId?: string
  onCancel: () => void
  onSuccess: (detail?: { created?: unknown }) => void | Promise<void>
}) {
  const { options: projectStyleOptions, defaultVisualStyle, getDefaultStyle } = useProjectStyleOptions()
  const [formName, setFormName] = useState('')
  const [formDesc, setFormDesc] = useState('')
  const [formTags, setFormTags] = useState('')
  const [formViewCount, setFormViewCount] = useState<number | null>(null)
  const [formVisualStyle, setFormVisualStyle] = useState<'现实' | '动漫'>(defaultVisualStyle as '现实' | '动漫')
  const [formStyle, setFormStyle] = useState<string>(getDefaultStyle(defaultVisualStyle))
  // 演员默认音色三件套：与角色音色同口径，但它是「这个人」的默认值，角色可覆盖。
  const [formVoiceId, setFormVoiceId] = useState<string | null>(null)
  const [formVoiceSource, setFormVoiceSource] = useState<VoiceSource | null>(null)
  const [formVoiceDesc, setFormVoiceDesc] = useState('')

  useEffect(() => {
    if (!open) return
    if (editing) {
      setFormName(editing.name)
      setFormDesc(editing.description ?? '')
      setFormTags((editing.tags ?? []).join(', '))
      setFormViewCount(editing.view_count ?? null)
      const nextVisual = ((editing.visual_style as '现实' | '动漫' | undefined) ?? defaultVisualStyle) as '现实' | '动漫'
      setFormVisualStyle(nextVisual)
      setFormStyle(
        (editing.style as string | undefined) ?? getDefaultStyle(nextVisual),
      )
      setFormVoiceId(editing.voice_id ?? null)
      setFormVoiceSource((editing.voice_source as VoiceSource | null) ?? null)
      setFormVoiceDesc(editing.voice_description ?? '')
    } else {
      setFormName('')
      setFormDesc('')
      setFormTags('')
      setFormViewCount(null)
      setFormVisualStyle(defaultVisualStyle as '现实' | '动漫')
      setFormStyle(getDefaultStyle(defaultVisualStyle))
      setFormVoiceId(null)
      setFormVoiceSource(null)
      setFormVoiceDesc('')
    }
  }, [open, editing, defaultVisualStyle, getDefaultStyle])

  const handleOk = async () => {
    const name = formName.trim()
    if (!name) {
      message.warning('请输入名称')
      return Promise.reject(new Error('validation'))
    }
    try {
      if (!editing) {
        const created = await StudioEntitiesApi.create('actor', {
          id: crypto?.randomUUID?.() ?? `actor_${Date.now()}`,
          name,
          description: formDesc.trim() || undefined,
          tags: normalizeTags(formTags),
          view_count: formViewCount ?? undefined,
          visual_style: formVisualStyle,
          style: formStyle,
          voice_id: formVoiceId || null,
          voice_source: formVoiceId ? (formVoiceSource ?? 'preset') : null,
          voice_description: formVoiceDesc.trim(),
          prompt_template_id: null,
          ...(linkProjectId ? { project_id: linkProjectId } : {}),
          ...(linkProjectId && linkChapterId ? { chapter_id: linkChapterId } : {}),
          ...(linkProjectId && linkShotId ? { shot_id: linkShotId } : {}),
        })
        message.success('创建成功')
        onCancel()
        await onSuccess({ created: created.data })
      } else {
        await StudioEntitiesApi.update('actor', editing.id, {
          name,
          description: formDesc.trim() || null,
          tags: normalizeTags(formTags),
          view_count: formViewCount ?? null,
          visual_style: formVisualStyle,
          style: formStyle,
          // 显式传 null 才会清空该列（后端用 model_dump(exclude_unset=True)）
          voice_id: formVoiceId || null,
          voice_source: formVoiceId ? (formVoiceSource ?? 'preset') : null,
          voice_description: formVoiceDesc.trim(),
        })
        message.success('更新成功')
        onCancel()
        await onSuccess()
      }
    } catch {
      message.error(editing ? '更新失败' : '创建失败')
      return Promise.reject(new Error('api'))
    }
  }

  return (
    <Modal
      title={editing ? '编辑演员' : '新建演员'}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText={editing ? '保存' : '创建'}
    >
      <div className="space-y-3">
        <div>
          <div className="text-sm text-gray-600 mb-1">名称</div>
          <Input value={formName} onChange={(e) => setFormName(e.target.value)} />
        </div>
        <div>
          <div className="text-sm text-gray-600 mb-1">描述</div>
          <Input.TextArea rows={3} value={formDesc} onChange={(e) => setFormDesc(e.target.value)} />
        </div>
        <div>
          <div className="text-sm text-gray-600 mb-1">标签（逗号分隔）</div>
          <Input value={formTags} onChange={(e) => setFormTags(e.target.value)} />
        </div>
        <div>
          <div className="text-sm text-gray-600 mb-1">视角数（可选）</div>
          <InputNumber className="w-full" min={1} max={4} value={formViewCount} onChange={(v) => setFormViewCount(v ?? null)} />
        </div>
        <div>
          <div className="text-sm text-gray-600 mb-1">视觉风格</div>
          <ProjectVisualStyleAndStyleFields
            visual_style={formVisualStyle}
            style={formStyle}
            options={projectStyleOptions}
            onChange={(next) => {
              setFormVisualStyle(next.visual_style)
              setFormStyle(next.style)
            }}
          />
        </div>
        {/*
          演员音色：它是该演员所演**全部角色**的默认音色。
          为什么必须在演员上配置：同一演员在多个角色里应保持同一声线，逐个角色配会重复且易漂移；
          角色页的音色字段用于「这个角色需要不一样的声音」时覆盖。
        */}
        <div>
          <div className="text-sm text-gray-600 mb-1">默认音色</div>
          <div className="flex gap-2">
            <Select
              className="w-28 shrink-0"
              value={formVoiceSource ?? 'preset'}
              onChange={(v) => setFormVoiceSource(v as VoiceSource)}
              options={[
                { value: 'preset', label: '预设音色' },
                { value: 'custom', label: '自定义音色' },
              ]}
            />
            <div className="flex-1 min-w-0">
              <VoiceSelectField
                value={formVoiceId}
                kind={formVoiceSource ?? 'preset'}
                onChange={({ voice_id, voice_source }) => {
                  setFormVoiceId(voice_id)
                  setFormVoiceSource(voice_source)
                }}
              />
            </div>
          </div>
          <Typography.Text type="secondary" className="text-xs">
            角色未单独配置音色时，配音将回退使用该演员音色。
          </Typography.Text>
        </div>
        <div>
          <div className="text-sm text-gray-600 mb-1">音色描述（选型参考）</div>
          <Input.TextArea
            rows={2}
            value={formVoiceDesc}
            onChange={(e) => setFormVoiceDesc(e.target.value)}
            placeholder="如：青年男性，声线偏低沉，语速中等，略带沙哑"
          />
        </div>
      </div>
    </Modal>
  )
}
