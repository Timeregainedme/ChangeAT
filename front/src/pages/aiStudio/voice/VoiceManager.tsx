import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import {
  StudioAudioTasksService,
  StudioProjectsService,
} from '../../../services/generated'
import type { VoiceItem } from '../../../services/generated'
import { StudioEntitiesApi } from '../../../services/studioEntities'
import { fetchAllPages } from '../../../services/paging'
import { VoiceSelectField, type VoiceSource } from '../components/VoiceSelectField'

/**
 * 从 generated client 抛出的错误里取出可展示的原因。
 *
 * 为什么需要：这些接口的失败原因都在后端 `detail` 里（例如 FastAPI 的参数校验
 * 说明、供应商不支持音色列表的 400 文案）。只显示一句「失败」会让用户无法区分
 * 「后端明确拒绝」和「网络断了」，也没法照着提示自己修。
 */
function describeError(error: unknown): string {
  const detail = (error as { body?: { detail?: unknown } })?.body?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (error instanceof Error && error.message) return error.message
  return '未知错误'
}

/**
 * 音色管理页。
 *
 * 为什么需要独立一页：音色此前散落在「角色编辑」里，只有配到某个角色时才看得见，
 * 用户无法回答三个基本问题 —— (1) 供应商到底有哪些音色可用？(2) 同一个演员在多个
 * 角色里是不是被配了不同音色？(3) 哪些角色压根没配音色、会静默回退到演员？
 * 本页用「音色列表」回答 (1)，用「绑定概览」回答 (2)(3)。
 *
 * 层级语义（决定本页的读写位置）：
 *   演员音色 = 该演员所演**全部角色**的默认音色（第一优先级，先在这一层配）
 *   角色音色 = 覆盖演员音色，仅在「这个角色需要不一样的声音」时才配
 *   两者都为空 → TTS 报 422，不会用任意音色兜底
 */

type ActorRow = {
  id: string
  name: string
  voice_id?: string | null
  voice_source?: string | null
  voice_description?: string | null
}

type CharacterRow = {
  id: string
  name: string
  project_id: string
  actor_id?: string | null
  voice_id?: string | null
  voice_source?: string | null
}

// 表格列的最小本地类型：antd 的 ColumnsType 泛型在这里只会带来类型噪音。
type Column<T> = {
  title: string
  key: string
  width?: number
  render: (_: unknown, row: T) => React.ReactNode
}

export default function VoiceManager() {
  const [kind, setKind] = useState<VoiceSource>('preset')
  const [voices, setVoices] = useState<VoiceItem[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  // 供应商未开放音色列表（非优云智算）时返回 400，这属预期降级而非故障，单独用文案区分。
  const [voicesError, setVoicesError] = useState<string | null>(null)
  const [voiceSearch, setVoiceSearch] = useState('')

  const [actors, setActors] = useState<ActorRow[]>([])
  const [characters, setCharacters] = useState<CharacterRow[]>([])
  const [projectNames, setProjectNames] = useState<Record<string, string>>({})
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [savingActorId, setSavingActorId] = useState<string | null>(null)

  const loadVoices = useCallback(async (nextKind: VoiceSource) => {
    setVoicesLoading(true)
    setVoicesError(null)
    try {
      const res = await StudioAudioTasksService.listAudioVoicesApiV1StudioAudioTasksVoicesGet({ kind: nextKind })
      setVoices((res.data ?? []) as VoiceItem[])
    } catch (error) {
      setVoicesError(describeError(error))
      setVoices([])
    } finally {
      setVoicesLoading(false)
    }
  }, [])

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true)
    try {
      // 一律按后端上限翻页取全量：直接传 pageSize > 100 会被 FastAPI 判 422
      // （`query.page_size: Input should be less than or equal to 100`）。
      const [actorList, characterList, projectList] = await Promise.all([
        fetchAllPages<ActorRow>((page, pageSize) =>
          StudioEntitiesApi.list('actor', {
            page,
            pageSize,
            q: null,
            order: 'updated_at',
            isDesc: true,
          }).then((res) => ({
            items: (res.data?.items ?? []) as ActorRow[],
            maxPage: res.data?.pagination?.max_page,
          })),
        ),
        fetchAllPages<CharacterRow>((page, pageSize) =>
          StudioEntitiesApi.list('character', { page, pageSize, q: null, order: null, isDesc: false }).then((res) => ({
            items: (res.data?.items ?? []) as CharacterRow[],
            maxPage: res.data?.pagination?.max_page,
          })),
        ),
        fetchAllPages<{ id: string; name?: string }>((page, pageSize) =>
          StudioProjectsService.listProjectsApiV1StudioProjectsGet({ page, pageSize, isDesc: false }).then((res) => ({
            items: (res.data?.items ?? []) as Array<{ id: string; name?: string }>,
            maxPage: res.data?.pagination?.max_page,
          })),
        ),
      ])
      setActors(actorList)
      setCharacters(characterList)
      const map: Record<string, string> = {}
      for (const p of projectList) {
        map[p.id] = p.name ?? p.id
      }
      setProjectNames(map)
    } catch (error) {
      message.error(`加载音色绑定概览失败：${describeError(error)}`)
    } finally {
      setOverviewLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadVoices(kind)
  }, [kind, loadVoices])

  useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  const actorById = useMemo(() => {
    const map = new Map<string, ActorRow>()
    actors.forEach((a) => map.set(a.id, a))
    return map
  }, [actors])

  /** 更新演员默认音色：显式传 null 才会清空（后端用 `model_dump(exclude_unset=True)`）。 */
  const handleSaveActorVoice = async (
    actorId: string,
    next: { voice_id: string | null; voice_source: VoiceSource | null },
  ) => {
    setSavingActorId(actorId)
    try {
      await StudioEntitiesApi.update('actor', actorId, {
        voice_id: next.voice_id,
        voice_source: next.voice_id ? (next.voice_source ?? 'preset') : null,
      })
      message.success('已更新演员默认音色')
      await loadOverview()
    } catch (error) {
      message.error(`更新演员音色失败：${describeError(error)}`)
    } finally {
      setSavingActorId(null)
    }
  }

  const filteredVoices = useMemo(() => {
    const kw = voiceSearch.trim().toLowerCase()
    if (!kw) return voices
    return voices.filter((v) => {
      const hay = `${v.voice_id ?? ''} ${v.name ?? ''} ${v.language ?? ''}`.toLowerCase()
      return hay.includes(kw)
    })
  }, [voices, voiceSearch])

  // 每个音色被哪些角色直接引用（用于在「音色列表」里直接看到占用情况）
  const charactersByVoiceId = useMemo(() => {
    const map = new Map<string, CharacterRow[]>()
    characters.forEach((c) => {
      if (!c.voice_id) return
      const arr = map.get(c.voice_id) ?? []
      arr.push(c)
      map.set(c.voice_id, arr)
    })
    return map
  }, [characters])

  const voiceColumns: Column<VoiceItem>[] = [
    {
      title: '音色名称',
      key: 'name',
      render: (_, row) => row.name || '—',
    },
    {
      title: 'voice_id',
      key: 'voice_id',
      render: (_, row) => <Typography.Text code>{row.voice_id || '—'}</Typography.Text>,
    },
    {
      title: '语言',
      key: 'language',
      width: 100,
      render: (_, row) => row.language || '—',
    },
    {
      title: '已被角色直接引用',
      key: 'used_by',
      render: (_, row) => {
        const used = charactersByVoiceId.get(row.voice_id ?? '') ?? []
        if (used.length === 0) return <Typography.Text type="secondary">无</Typography.Text>
        return (
          <Space size={4} wrap>
            {used.slice(0, 4).map((c) => (
              <Tag key={c.id} color="blue">
                {c.name}
              </Tag>
            ))}
            {used.length > 4 ? <Typography.Text type="secondary">+{used.length - 4}</Typography.Text> : null}
          </Space>
        )
      },
    },
  ]

  const actorColumns: Column<ActorRow>[] = [
    { title: '演员', key: 'name', width: 160, render: (_, row) => row.name },
    {
      title: '默认音色',
      key: 'voice',
      width: 320,
      render: (_, row) => (
        <VoiceSelectField
          value={row.voice_id ?? null}
          kind={(row.voice_source as VoiceSource | null) ?? kind}
          disabled={savingActorId === row.id}
          onChange={(next) => void handleSaveActorVoice(row.id, next)}
        />
      ),
    },
    {
      title: '音色描述',
      key: 'desc',
      render: (_, row) =>
        row.voice_description ? (
          <Typography.Text type="secondary" className="text-xs">
            {row.voice_description}
          </Typography.Text>
        ) : (
          '—'
        ),
    },
  ]

  const characterColumns: Column<CharacterRow>[] = [
    { title: '角色', key: 'name', width: 140, render: (_, row) => row.name },
    {
      title: '项目',
      key: 'project',
      width: 160,
      render: (_, row) => projectNames[row.project_id] ?? row.project_id,
    },
    {
      title: '角色音色',
      key: 'voice',
      width: 180,
      render: (_, row) =>
        row.voice_id ? <Tag color="blue">{row.voice_id}</Tag> : <Tag>未配置</Tag>,
    },
    {
      title: '实际生效音色',
      key: 'effective',
      render: (_, row) => {
        if (row.voice_id) return <Typography.Text>角色音色（覆盖演员）</Typography.Text>
        const actor = row.actor_id ? actorById.get(row.actor_id) : undefined
        if (actor?.voice_id) {
          return (
            <Typography.Text>
              回退演员「{actor.name}」的音色 <Typography.Text code>{actor.voice_id}</Typography.Text>
            </Typography.Text>
          )
        }
        return (
          <Typography.Text type="warning">
            无（角色未配置且关联演员也未配置音色）→ 配音时会直接报错
          </Typography.Text>
        )
      },
    },
  ]

  return (
    <div className="p-4 space-y-4 overflow-auto h-full">
      <Card
        title="音色管理"
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void loadVoices(kind)
              void loadOverview()
            }}
          >
            刷新
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" className="text-xs">
          音色分两层：<strong>演员音色</strong>是该演员所演全部角色的默认音色；
          <strong>角色音色</strong>可覆盖演员音色。两者都为空时配音任务会显式报错，不会静默使用任意音色。
          音色列表来自默认音频模型供应商（当前仅优云智算 IndexTTS 提供列表接口）。
        </Typography.Paragraph>

        <Tabs
          items={[
            {
              key: 'voices',
              label: '音色列表',
              children: (
                <div className="space-y-3">
                  <Space>
                    <Select
                      value={kind}
                      style={{ width: 140 }}
                      onChange={(v) => setKind(v as VoiceSource)}
                      options={[
                        { value: 'preset', label: '预设音色' },
                        { value: 'custom', label: '自定义音色' },
                      ]}
                    />
                    <Input.Search
                      allowClear
                      placeholder="搜索名称 / voice_id / 语言"
                      style={{ width: 280 }}
                      value={voiceSearch}
                      onChange={(e) => setVoiceSearch(e.target.value)}
                    />
                  </Space>
                  {voicesError ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        <span>
                          该音色列表不可用：{voicesError}
                          <br />
                          请到「模型管理」确认默认音频模型供应商支持音色列表接口。
                        </span>
                      }
                    />
                  ) : (
                    <Table
                      rowKey={(row) => row.voice_id ?? Math.random().toString()}
                      size="small"
                      loading={voicesLoading}
                      columns={voiceColumns}
                      dataSource={filteredVoices}
                      pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个音色` }}
                    />
                  )}
                </div>
              ),
            },
            {
              key: 'actors',
              label: '演员默认音色',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={overviewLoading}
                  columns={actorColumns}
                  dataSource={actors}
                  pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 位演员` }}
                />
              ),
            },
            {
              key: 'characters',
              label: '角色生效音色',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={overviewLoading}
                  columns={characterColumns}
                  dataSource={characters}
                  pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个角色` }}
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
