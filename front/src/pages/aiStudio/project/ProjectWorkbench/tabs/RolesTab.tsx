import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, Button, Empty, Modal, Input, message, Space, Select, Pagination, Tag } from 'antd'
import { EditOutlined, PlusOutlined, PictureOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  StudioProjectsService,
  StudioShotLinksService,
} from '../../../../../services/generated'
import type { ProjectActorLinkRead, ProjectCostumeLinkRead } from '../../../../../services/generated'
import { useProjectCharacters, newId } from '../hooks/useProjectData'
import { resolveAssetUrl } from '../../../assets/utils'
import { DisplayImageCard } from '../../../assets/components/DisplayImageCard'
import { StudioEntitiesApi } from '../../../../../services/studioEntities'
import {
  ProjectVisualStyleAndStyleFields,
  type ProjectVisualStyleChoice,
  type ProjectStyleFieldOptions,
} from '../../../project/ProjectVisualStyleAndStyleFields'
import { useProjectStyleOptions } from '../../../project/useProjectStyleOptions'
import { VoiceSelectField, type VoiceSource } from '../../../components/VoiceSelectField'
import { BatchAssetImageButton } from '../../../components/BatchAssetImageButton'

type ActorLike = {
  id: string
  name: string
  description?: string | null
  thumbnail?: string
}

type CostumeLike = {
  id: string
  name: string
  description?: string | null
  thumbnail?: string
}

/** 带 JSX label 的下拉选项（演员选项需要显示头像，故不能用纯字符串 label）。 */
type SelectOption = {
  value: string
  label: React.ReactNode
  searchLabel: string
}

/**
 * 角色表单的受控值集合。
 *
 * 为什么存在：新建与编辑用的是**同一套字段**（名称/描述/风格/演员/服装/音色），
 * 抽成一个值对象后两种模式共用一个 `RoleFormFields`，避免出现「能建不能改」
 * 或「改了但漏字段」这类两侧漂移的缺陷。
 */
type RoleFormValues = {
  name: string
  description: string
  visualStyle: ProjectVisualStyleChoice
  style: string
  actorId: string | undefined
  costumeId: string | undefined
  voiceId: string | null
  voiceSource: VoiceSource | null
  voiceDescription: string
}

const EMPTY_ROLE_FORM: RoleFormValues = {
  name: '',
  description: '',
  visualStyle: '现实',
  style: '',
  actorId: undefined,
  costumeId: undefined,
  voiceId: null,
  voiceSource: null,
  voiceDescription: '',
}

type RoleFormFieldsProps = {
  values: RoleFormValues
  onChange: (patch: Partial<RoleFormValues>) => void
  actorOptions: SelectOption[]
  costumeOptions: SelectOption[]
  loadingLinks: boolean
  projectStyleOptions: ProjectStyleFieldOptions
  /** 项目内与当前输入同名的演员 ID（用于「按同名匹配」建议，用户确认后才写入） */
  sameNameActorId?: string
  onAcceptSameNameActor?: (actorId: string) => void
  /** 编辑模式下音色描述由剧本提取产出，展示时给出来源提示 */
  showVoiceDescriptionHint?: boolean
}

/**
 * 角色表单字段（新建 / 编辑共用）。
 *
 * 字段顺序遵循用户填写心智：先身份（名称/描述/风格），再形象来源（演员/服装），
 * 最后音色。演员与服装都必须来自**当前项目已关联**的资产，否则角色图会缺参考图。
 */
function RoleFormFields({
  values,
  onChange,
  actorOptions,
  costumeOptions,
  loadingLinks,
  projectStyleOptions,
  sameNameActorId,
  onAcceptSameNameActor,
  showVoiceDescriptionHint,
}: RoleFormFieldsProps) {
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm text-gray-600 mb-1">角色名称</div>
        <Input
          value={values.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="例如：小雨"
        />
      </div>
      <div>
        <div className="text-sm text-gray-600 mb-1">描述（可选）</div>
        <Input.TextArea
          rows={3}
          value={values.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </div>
      <div>
        <ProjectVisualStyleAndStyleFields
          visual_style={values.visualStyle}
          style={values.style}
          options={projectStyleOptions}
          onChange={(next) => onChange({ visualStyle: next.visual_style, style: next.style })}
        />
      </div>
      <div>
        <div className="text-sm text-gray-600 mb-1">关联演员（必填）</div>
        <Select
          className="w-full"
          placeholder="选择当前项目已关联的演员"
          loading={loadingLinks}
          value={values.actorId}
          onChange={(v) => onChange({ actorId: v })}
          options={actorOptions}
          showSearch
          optionFilterProp="searchLabel"
          filterOption={(input, option) => String(option?.searchLabel ?? '').toLowerCase().includes(input.toLowerCase())}
        />
        {sameNameActorId && sameNameActorId !== values.actorId && onAcceptSameNameActor ? (
          <div className="mt-1">
            <Button
              type="link"
              size="small"
              className="px-0"
              onClick={() => onAcceptSameNameActor(sameNameActorId)}
            >
              检测到项目内有同名演员，一键绑定
            </Button>
          </div>
        ) : null}
        <div className="text-xs text-gray-500 mt-1">
          角色图会同时引用「该演员的参考图」与「该服装的参考图」。系统不做名字匹配，
          名字相同也要在这里显式绑定。
        </div>
      </div>
      <div>
        <div className="text-sm text-gray-600 mb-1">关联服装（可选）</div>
        <Select
          className="w-full"
          allowClear
          placeholder="选择当前项目已关联的服装"
          loading={loadingLinks}
          value={values.costumeId}
          onChange={(v) => onChange({ costumeId: v })}
          options={costumeOptions}
          showSearch
          optionFilterProp="searchLabel"
          filterOption={(input, option) => String(option?.searchLabel ?? '').toLowerCase().includes(input.toLowerCase())}
        />
      </div>
      <div>
        <div className="text-sm text-gray-600 mb-1">音色类型</div>
        <Select
          className="w-full"
          value={values.voiceSource ?? 'preset'}
          onChange={(v: VoiceSource) => onChange({ voiceSource: v })}
          options={[
            { value: 'preset', label: '预置音色（preset）' },
            { value: 'custom', label: '自定义复刻音色（custom）' },
          ]}
        />
      </div>
      <div>
        <div className="text-sm text-gray-600 mb-1">绑定音色（可选）</div>
        <VoiceSelectField
          value={values.voiceId}
          kind={values.voiceSource ?? 'preset'}
          onChange={({ voice_id, voice_source }) =>
            onChange({ voiceId: voice_id, voiceSource: voice_source ?? values.voiceSource })
          }
        />
        <div className="text-xs text-gray-500 mt-1">
          角色未单独配音色时，TTS 会回退到该演员的音色；两者都没有才会报错。
        </div>
      </div>
      <div>
        <div className="text-sm text-gray-600 mb-1">音色描述（可选）</div>
        <Input.TextArea
          rows={2}
          value={values.voiceDescription}
          onChange={(e) => onChange({ voiceDescription: e.target.value })}
          placeholder="例如：青年女性，声线清亮偏甜，语速偏快"
        />
        {showVoiceDescriptionHint ? (
          <div className="text-xs text-gray-500 mt-1">
            该字段通常由剧本提取自动产出，可在此人工修正。
          </div>
        ) : null}
      </div>
    </div>
  )
}

function notifyShotAssetCreatedAndLinked(payload: {
  projectId?: string
  chapterId?: string | null
  shotId?: string | null
  assetId?: string
  assetName: string
}) {
  if (!payload.projectId || !payload.chapterId || !payload.shotId) return
  try {
    window.opener?.postMessage(
      {
        type: 'studio-shot-asset-created-and-linked',
        projectId: payload.projectId,
        chapterId: payload.chapterId,
        shotId: payload.shotId,
        assetId: payload.assetId ?? null,
        assetName: payload.assetName,
      },
      window.location.origin,
    )
  } catch {
    // 跨窗口通知失败不阻塞角色创建成功。
  }
}

export function RolesTab() {
  const { options: projectStyleOptions, defaultVisualStyle, getDefaultStyle } = useProjectStyleOptions()
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const { characters, loading, refresh } = useProjectCharacters(projectId)

  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [pendingShotLinkShotId, setPendingShotLinkShotId] = useState<string | null>(null)
  const [pendingShotLinkChapterId, setPendingShotLinkChapterId] = useState<string | null>(null)
  const [createForm, setCreateForm] = useState<RoleFormValues>(EMPTY_ROLE_FORM)

  const [editOpen, setEditOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<RoleFormValues>(EMPTY_ROLE_FORM)

  const [projectActorLinks, setProjectActorLinks] = useState<ProjectActorLinkRead[]>([])
  const [projectCostumeLinks, setProjectCostumeLinks] = useState<ProjectCostumeLinkRead[]>([])
  const [actorsById, setActorsById] = useState<Record<string, ActorLike>>({})
  const [costumesById, setCostumesById] = useState<Record<string, CostumeLike>>({})
  const [loadingLinks, setLoadingLinks] = useState(false)
  const [projectVisualStyle, setProjectVisualStyle] = useState<ProjectVisualStyleChoice>(defaultVisualStyle as ProjectVisualStyleChoice)
  const [projectStyle, setProjectStyle] = useState<string>(getDefaultStyle(defaultVisualStyle))

  useEffect(() => {
    const create = searchParams.get('create')
    const name = searchParams.get('name') ?? ''
    const desc = searchParams.get('desc') ?? ''
    const tab = searchParams.get('tab')
    const visualStyle = (searchParams.get('visualStyle')?.trim() || '') as ProjectVisualStyleChoice | ''
    const style = searchParams.get('style')?.trim() ?? ''
    if (create === '1' && tab === 'roles') {
      const nextVisual = visualStyle || projectVisualStyle
      setCreateForm({
        ...EMPTY_ROLE_FORM,
        name,
        description: desc,
        visualStyle: nextVisual,
        style: style || projectStyle || getDefaultStyle(nextVisual),
      })
      const shotIdFromUrl = searchParams.get('shotId')?.trim() ?? ''
      const chapterIdFromUrl = searchParams.get('chapterId')?.trim() ?? ''
      setPendingShotLinkShotId(shotIdFromUrl || null)
      setPendingShotLinkChapterId(chapterIdFromUrl || null)
      setCreateOpen(true)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('create')
          next.delete('name')
          next.delete('desc')
          next.delete('chapterId')
          next.delete('shotId')
          next.delete('visualStyle')
          next.delete('style')
          return next
        },
        { replace: true },
      )
    }
  }, [getDefaultStyle, projectStyle, projectVisualStyle, searchParams, setSearchParams])

  const openNormalRoleCreate = useCallback(() => {
    setPendingShotLinkShotId(null)
    setPendingShotLinkChapterId(null)
    setCreateForm({
      ...EMPTY_ROLE_FORM,
      visualStyle: projectVisualStyle,
      style: projectStyle,
    })
    setCreateOpen(true)
  }, [projectStyle, projectVisualStyle])

  const loadProjectLinks = async () => {
    if (!projectId) return
    setLoadingLinks(true)
    try {
      const [actorRes, costumeRes] = await Promise.all([
        StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
          entityType: 'actor',
          projectId,
          chapterId: null,
          shotId: null,
          assetId: null,
          order: null,
          isDesc: false,
          page: 1,
          pageSize: 100,
        }),
        StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
          entityType: 'costume',
          projectId,
          chapterId: null,
          shotId: null,
          assetId: null,
          order: null,
          isDesc: false,
          page: 1,
          pageSize: 100,
        }),
      ])
      const actorLinks = (actorRes.data?.items ?? []) as ProjectActorLinkRead[]
      const costumeLinks = (costumeRes.data?.items ?? []) as ProjectCostumeLinkRead[]
      setProjectActorLinks(actorLinks)
      setProjectCostumeLinks(costumeLinks)

      const actorIds = Array.from(new Set(actorLinks.map((l) => l.actor_id)))
      const costumeIds = Array.from(new Set(costumeLinks.map((l) => l.costume_id)))

      const [actors, costumes] = await Promise.all([
        Promise.all(
          actorIds.map((id) =>
            StudioEntitiesApi.get('actor', id)
              .then((r) => (r.data ?? null) as ActorLike | null)
              .catch(() => null),
          ),
        ),
        Promise.all(
          costumeIds.map((id) =>
            StudioEntitiesApi.get('costume', id)
              .then((r) => (r.data ?? null) as CostumeLike | null)
              .catch(() => null),
          ),
        ),
      ])

      const nextActors: Record<string, ActorLike> = {}
      actors.filter(Boolean).forEach((a) => {
        nextActors[(a as ActorLike).id] = a as ActorLike
      })
      const nextCostumes: Record<string, CostumeLike> = {}
      costumes.filter(Boolean).forEach((c) => {
        nextCostumes[(c as CostumeLike).id] = c as CostumeLike
      })
      setActorsById(nextActors)
      setCostumesById(nextCostumes)
    } catch {
      message.error('加载项目关联演员/服装失败')
      setProjectActorLinks([])
      setProjectCostumeLinks([])
      setActorsById({})
      setCostumesById({})
    } finally {
      setLoadingLinks(false)
    }
  }

  useEffect(() => {
    void loadProjectLinks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    void (async () => {
      try {
        const res = await StudioProjectsService.getProjectApiV1StudioProjectsProjectIdGet({ projectId })
        const nextVisual = (res.data?.visual_style as ProjectVisualStyleChoice | undefined) ?? (defaultVisualStyle as ProjectVisualStyleChoice)
        const nextStyle = (res.data?.style as string | undefined) ?? getDefaultStyle(nextVisual)
        setProjectVisualStyle(nextVisual)
        setProjectStyle(nextStyle)
      } catch {
        // ignore: fallback to default
      }
    })()
  }, [defaultVisualStyle, getDefaultStyle, projectId])

  const handleCreateRole = async () => {
    if (!projectId) return
    const name = createForm.name.trim()
    if (!name) {
      message.warning('请输入角色名称')
      return
    }
    if (!createForm.actorId) {
      message.warning('请选择关联演员')
      return
    }
    setCreating(true)
    try {
      const createRes = await StudioEntitiesApi.create('character', {
        id: newId('char'),
        project_id: projectId,
        chapter_id: pendingShotLinkChapterId,
        shot_id: pendingShotLinkShotId,
        name,
        description: createForm.description.trim() || undefined,
        visual_style: createForm.visualStyle || '现实',
        style: createForm.style,
        actor_id: createForm.actorId,
        costume_id: createForm.costumeId ?? null,
        voice_id: createForm.voiceId || null,
        voice_source: createForm.voiceSource ?? null,
        voice_description: createForm.voiceDescription.trim(),
      })
      const charId = (createRes.data as { id?: string } | undefined)?.id
      if (charId && pendingShotLinkShotId) {
        notifyShotAssetCreatedAndLinked({
          projectId,
          chapterId: pendingShotLinkChapterId,
          shotId: pendingShotLinkShotId,
          assetId: charId,
          assetName: name,
        })
      }
      message.success('角色创建成功')
      setCreateOpen(false)
      setCreateForm(EMPTY_ROLE_FORM)
      setPendingShotLinkShotId(null)
      setPendingShotLinkChapterId(null)
      await refresh()
    } catch {
      message.error('创建失败')
      setPendingShotLinkShotId(null)
      setPendingShotLinkChapterId(null)
    } finally {
      setCreating(false)
    }
  }

  /**
   * 打开「编辑角色」弹窗。
   *
   * 为什么存在：卡片上的「编辑」此前直接跳到资产编辑页（只有图片槽位与提示词），
   * 用户因此完全无法修改角色的名称/演员/服装/音色（连创建时选过的演员也改不了）。
   * 这里把「角色信息编辑」与「立绘编辑」拆成两个入口：本弹窗负责前者，
   * 卡片上的「立绘」按钮负责后者。
   */
  const openRoleEdit = useCallback((character: Record<string, unknown>) => {
    setEditingId(String(character.id ?? ''))
    setEditForm({
      name: String(character.name ?? ''),
      description: String(character.description ?? ''),
      visualStyle: ((character.visual_style as ProjectVisualStyleChoice | undefined) ?? projectVisualStyle),
      style: String(character.style ?? projectStyle),
      actorId: (character.actor_id as string | null | undefined) ?? undefined,
      costumeId: (character.costume_id as string | null | undefined) ?? undefined,
      voiceId: (character.voice_id as string | null | undefined) ?? null,
      voiceSource: (character.voice_source as VoiceSource | null | undefined) ?? null,
      voiceDescription: String(character.voice_description ?? ''),
    })
    setEditOpen(true)
  }, [projectStyle, projectVisualStyle])

  const handleUpdateRole = async () => {
    if (!editingId) return
    const name = editForm.name.trim()
    if (!name) {
      message.warning('请输入角色名称')
      return
    }
    if (!editForm.actorId) {
      message.warning('请选择关联演员')
      return
    }
    setSaving(true)
    try {
      await StudioEntitiesApi.update('character', editingId, {
        name,
        description: editForm.description.trim(),
        visual_style: editForm.visualStyle || '现实',
        style: editForm.style,
        actor_id: editForm.actorId,
        costume_id: editForm.costumeId ?? null,
        // 显式传 null 才会清空（后端用 model_dump(exclude_unset=True) 判定是否改动）。
        voice_id: editForm.voiceId || null,
        voice_source: editForm.voiceSource ?? null,
        voice_description: editForm.voiceDescription.trim(),
      })
      message.success('角色已更新')
      setEditOpen(false)
      setEditingId(null)
      await refresh()
    } catch {
      message.error('更新失败')
    } finally {
      setSaving(false)
    }
  }

  const roleCards = useMemo(() => {
    return characters.map((c) => {
      const actor = actorsById[c.actor_id]
      const costume = c.costume_id ? costumesById[c.costume_id] : undefined
      return { c, actor, costume }
    })
  }, [actorsById, characters, costumesById])

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const pagedRoleCards = useMemo(() => {
    const start = (page - 1) * pageSize
    return roleCards.slice(start, start + pageSize)
  }, [page, pageSize, roleCards])

  useEffect(() => {
    setPage(1)
  }, [roleCards.length])

  const actorOptions: SelectOption[] = useMemo(() => {
    return projectActorLinks.map((l) => {
      const a = actorsById[l.actor_id]
      const url = resolveAssetUrl(a?.thumbnail)
      return {
        value: l.actor_id,
        searchLabel: a?.name ?? l.actor_id,
        label: (
          <div className="flex items-center gap-2 min-w-0">
            {url ? (
              <img src={url} alt="" className="w-6 h-6 rounded object-cover shrink-0" />
            ) : (
              <div className="w-6 h-6 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                <UserOutlined />
              </div>
            )}
            <div className="min-w-0 truncate">{a?.name ?? l.actor_id}</div>
          </div>
        ),
      }
    })
  }, [actorsById, projectActorLinks])

  const costumeOptions: SelectOption[] = useMemo(() => {
    return projectCostumeLinks.map((l) => {
      const c = costumesById[l.costume_id]
      return { value: l.costume_id, label: c?.name ?? l.costume_id, searchLabel: c?.name ?? l.costume_id }
    })
  }, [costumesById, projectCostumeLinks])

  /**
   * 按同名找演员：仅作为**建议**，绝不自动写入。
   *
   * 为什么不做静默绑定：演员是「外形素材」、角色是「戏中身份」，同一演员可演多个角色、
   * 不同演员也可能重名，靠名字自动绑定会把人绑错。这里只把同名候选提示给用户，
   * 由用户点按钮确认。
   */
  const findActorIdByName = useCallback(
    (name: string, options: SelectOption[]): string | undefined => {
      const target = name.trim()
      if (!target) return undefined
      const hit = options.find((o) => o.searchLabel.trim() === target)
      return hit?.value
    },
    [],
  )

  if (!projectId) {
    return null
  }

  const createSameNameActorId = findActorIdByName(createForm.name, actorOptions)
  const editSameNameActorId = findActorIdByName(editForm.name, actorOptions)

  return (
    <div className="h-full overflow-auto">
      <Card
        title="项目角色"
        extra={
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={openNormalRoleCreate}>
              新建角色
            </Button>
            {/*
              角色图会引用「该角色绑定的演员图 + 服装图」。放在这里让用户能一键重跑全部角色图，
              但确认框里必须提示依赖顺序（演员/服装先出图），否则会在零参考图下静默生成。
            */}
            <BatchAssetImageButton
              projectId={projectId}
              assetType="character"
              assetCount={characters.length}
              onFinished={() => void refresh()}
            />
          </Space>
        }
      >
        {characters.length === 0 && !loading ? (
          <Empty
            description="暂无项目角色"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Space>
              <Button type="primary" icon={<PlusOutlined />} onClick={openNormalRoleCreate}>
                新建角色
              </Button>
            </Space>
          </Empty>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {pagedRoleCards.map(({ c, actor, costume }) => (
              <DisplayImageCard
                key={c.id}
                title={<div className="truncate">{c.name}</div>}
                imageUrl={resolveAssetUrl(c.thumbnail)}
                imageAlt={c.name}
                enablePreview
                extra={
                  <Space size="small">
                    <Button
                      type="default"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => openRoleEdit(c)}
                    >
                      编辑
                    </Button>
                    <Button
                      type="default"
                      size="small"
                      icon={<PictureOutlined />}
                      onClick={() => {
                        if (!projectId) return
                        navigate(`/projects/${projectId}/roles/${c.id}/edit`)
                      }}
                    >
                      立绘
                    </Button>
                    <Button
                      size="small"
                      danger
                      onClick={() => {
                        Modal.confirm({
                          title: `删除角色「${c.name}」？`,
                          okText: '删除',
                          cancelText: '取消',
                          okButtonProps: { danger: true },
                          onOk: async () => {
                            try {
                              await StudioEntitiesApi.remove('character', c.id)
                              message.success('已删除')
                              await refresh()
                            } catch {
                              message.error('删除失败')
                            }
                          },
                        })
                      }}
                    >
                      删除
                    </Button>
                  </Space>
                }
                meta={
                  <div className="space-y-1">
                    {c.description ? <div className="text-xs text-gray-600 line-clamp-2">{c.description}</div> : null}
                    <div className="text-xs text-gray-500 truncate">
                      演员：{actor?.name ?? c.actor_id ?? '未绑定'}
                    </div>
                    <div className="text-xs text-gray-500 truncate">
                      服装：{costume?.name ?? (c.costume_id ?? '未绑定')}
                    </div>
                    <div className="text-xs text-gray-500 truncate">
                      音色：{c.voice_id ? <Tag color="blue">{c.voice_id}</Tag> : <Tag>未绑定（回退演员）</Tag>}
                    </div>
                  </div>
                }
              />
            ))}
            </div>
            <div className="flex justify-end">
              <Pagination
                current={page}
                pageSize={pageSize}
                total={roleCards.length}
                showSizeChanger={false}
                showTotal={(t) => `共 ${t} 条`}
                onChange={(p, ps) => {
                  setPage(p)
                  setPageSize(ps)
                }}
              />
            </div>
          </div>
        )}
      </Card>

      <Modal
        title="新建角色"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false)
          setPendingShotLinkShotId(null)
        }}
        onOk={handleCreateRole}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
        width={560}
      >
        <RoleFormFields
          values={createForm}
          onChange={(patch) => setCreateForm((prev) => ({ ...prev, ...patch }))}
          actorOptions={actorOptions}
          costumeOptions={costumeOptions}
          loadingLinks={loadingLinks}
          projectStyleOptions={projectStyleOptions}
          sameNameActorId={createSameNameActorId}
          onAcceptSameNameActor={(actorId) => setCreateForm((prev) => ({ ...prev, actorId }))}
        />
      </Modal>

      <Modal
        title="编辑角色"
        open={editOpen}
        onCancel={() => {
          setEditOpen(false)
          setEditingId(null)
        }}
        onOk={handleUpdateRole}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        width={560}
      >
        <RoleFormFields
          values={editForm}
          onChange={(patch) => setEditForm((prev) => ({ ...prev, ...patch }))}
          actorOptions={actorOptions}
          costumeOptions={costumeOptions}
          loadingLinks={loadingLinks}
          projectStyleOptions={projectStyleOptions}
          sameNameActorId={editSameNameActorId}
          onAcceptSameNameActor={(actorId) => setEditForm((prev) => ({ ...prev, actorId }))}
          showVoiceDescriptionHint
        />
      </Modal>
    </div>
  )
}
