import { useState, useEffect, useMemo, useRef } from 'react'
import { Card, Button, Tag, Space, Table, Empty, Modal, Input, Dropdown, message, Tooltip } from 'antd'
import type { MenuProps, TableColumnsType } from 'antd'
import {
  AppstoreOutlined,
  EditOutlined,
  FileSearchOutlined,
  LoadingOutlined,
  MoreOutlined,
  PlusOutlined,
  ScissorOutlined,
  StopOutlined,
  CheckSquareOutlined,
  SoundOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ScriptProcessingService,
  StudioChaptersService,
  StudioShotsService,
} from '../../../../../services/generated'
import { runSpeechTaskForLine } from '../../../shots/tts'
import { chapterStatusMap } from '../constants'
import { getChapterBoardPath, getChapterReviewPath, getChapterShotsPath, getChapterStudioPath } from '../routes'
import { useChapters, newId, type Chapter } from '../hooks/useProjectData'
import { ChapterRawTextEditorModal } from '../../../chapter/components/ChapterRawTextEditorModal'
import { ChapterPrepareWizard } from '../../../chapter/components/ChapterPrepareWizard'
import { ensureHasShotsBeforeShooting } from '../ensureHasShotsBeforeShooting'
import { getChapterPreparationState } from '../chapterPreparation'
import { loadChapterFlowStats, type ChapterFlowStats } from '../projectFlowStats'
import { executeAsyncTaskCreate, executeTaskCancel } from '../../../components/taskActionHelpers'
import { TASK_COPY } from '../../../components/taskCopy'
import { useTaskPageContext } from '../../../components/taskPageContext'
import { useTaskUiStore } from '../../../components/taskUiStore'
import {
  createRelationTaskState,
  upsertRelationTaskStateInMap,
  useChapterDivisionTaskMapPolling,
} from '../chapterDivisionTasks'

const { TextArea } = Input
const CREATE_PARAM = 'create'
const EDIT_PARAM = 'edit'

export function ChaptersTab() {
  const taskCopy = TASK_COPY.chapterDivision
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const { chapters, loading, refresh, patchChapterLocal } = useChapters(projectId)

  const [editOpen, setEditOpen] = useState(false)
  const [editingChapter, setEditingChapter] = useState<Chapter | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createTitle, setCreateTitle] = useState('')
  const [createContent, setCreateContent] = useState('')
  const [chapterFlowMap, setChapterFlowMap] = useState<Record<string, ChapterFlowStats>>({})
  const [chapterDivisionActionId, setChapterDivisionActionId] = useState<string | null>(null)
  const taskUiUpsert = useTaskUiStore((state) => state.upsertTask)
  const taskUiRemove = useTaskUiStore((state) => state.removeTask)
  const syncedTaskIdsRef = useRef<string[]>([])
  const chapterIds = useMemo(() => chapters.map((chapter) => chapter.id), [chapters])
  useTaskPageContext(
    chapterIds.map((id) => ({
      relationType: 'chapter_division',
      relationEntityId: id,
    })),
  )
    /** 一键准备向导：保存待处理的章节，null 表示关闭 */
  const [prepareChapter, setPrepareChapter] = useState<Chapter | null>(null)
  /** 章节级一键配音：正在执行的章节 id */
  const [chapterAudioRunningId, setChapterAudioRunningId] = useState<string | null>(null)

const { taskMap: chapterDivisionTaskMap, setTrackedTaskMap: setChapterDivisionTaskMap } = useChapterDivisionTaskMapPolling({
    chapterIds,
    onTasksSettled: async () => {
      await refresh()
    },
  })

  const createParam = searchParams.get(CREATE_PARAM)
  const editParam = searchParams.get(EDIT_PARAM)
  useEffect(() => {
    if (createParam === '1') {
      setCreateOpen(true)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete(CREATE_PARAM)
          return next
        },
        { replace: true }
      )
    }
  }, [createParam, setSearchParams])

  useEffect(() => {
    if (!editParam) return
    const target = chapters.find((chapter) => chapter.id === editParam)
    if (!target) return
    openEditModal(target)
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete(EDIT_PARAM)
        return next
      },
      { replace: true }
    )
  }, [chapters, editParam, setSearchParams])

  useEffect(() => {
    let cancelled = false
    if (!chapters.length) {
      setChapterFlowMap({})
      return () => {
        cancelled = true
      }
    }

    const run = async () => {
      try {
        const rows = await loadChapterFlowStats(chapters)
        if (!cancelled) {
          setChapterFlowMap(Object.fromEntries(rows.map((row) => [row.chapterId, row])))
        }
      } catch {
        if (!cancelled) setChapterFlowMap({})
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [chapters])

  const openEditModal = (chapter: Chapter) => {
    setEditingChapter(chapter)
    setEditOpen(true)
  }

  const openCreateNextStep = (chapter: Chapter, hasRawText: boolean) => {
    if (!projectId) return
    Modal.confirm({
      title: '章节创建成功',
      content: hasRawText
        ? '这一章已经有原文内容，接下来更适合直接提取分镜。'
        : '这一章还没有原文内容，建议先补章节原文。',
      okText: hasRawText ? '立即提取分镜' : '继续编辑原文',
      cancelText: '稍后处理',
      onOk: () => {
        if (hasRawText) {
          navigate(getChapterShotsPath(projectId, chapter.id))
          return
        }
        openEditModal(chapter)
      },
    })
  }

  const handleCreateChapter = async () => {
    if (!createTitle.trim()) {
      message.warning('请输入章节标题')
      return
    }
    if (!projectId) return
    try {
      const nextIndex = Math.max(0, ...chapters.map((c) => c.index)) + 1
      const createdId = newId('c')
      const title = createTitle.trim()
      const rawText = createContent
      const draftChapter: Chapter = {
        id: createdId,
        projectId,
        index: nextIndex,
        title,
        summary: '',
        rawText,
        storyboardCount: 0,
        status: 'draft',
        updatedAt: new Date().toISOString(),
      }
      await StudioChaptersService.createChapterApiV1StudioChaptersPost({
        requestBody: {
          id: createdId,
          project_id: projectId,
          index: nextIndex,
          title,
          summary: '',
          raw_text: rawText || undefined,
          storyboard_count: 0,
          status: 'draft',
        },
      })
      message.success('章节创建成功')
      setCreateOpen(false)
      setCreateTitle('')
      setCreateContent('')
      await refresh()
      openCreateNextStep(draftChapter, !!rawText.trim())
    } catch {
      message.error('创建章节失败')
    }
  }

  const useMock = import.meta.env.VITE_USE_MOCK === 'true'
  const handleCreateChapterMock = () => {
    if (!createTitle.trim()) {
      message.warning('请输入章节标题')
      return
    }
    if (!projectId) return
    const nextIndex = Math.max(0, ...chapters.map((c) => c.index)) + 1
    const createdId = newId('c')
    const title = createTitle.trim()
    const rawText = createContent
    const draftChapter: Chapter = {
      id: createdId,
      projectId,
      index: nextIndex,
      title,
      summary: '',
      rawText,
      storyboardCount: 0,
      status: 'draft',
      updatedAt: new Date().toISOString(),
    }
    message.success('创建成功（Mock）')
    setCreateOpen(false)
    setCreateTitle('')
    setCreateContent('')
    window.setTimeout(() => openCreateNextStep(draftChapter, !!rawText.trim()), 0)
    void refresh()
  }

  const handlePrimaryAction = (record: Chapter) => {
    if (!projectId) return
    const activeTask = chapterDivisionTaskMap[record.id]
    if (activeTask) {
      navigate(getChapterShotsPath(projectId, record.id))
      return
    }
    const state = getChapterPreparationState(record)
    if (state.key === 'edit_raw') {
      openEditModal(record)
      return
    }
    if (state.key === 'extract_shots') {
      navigate(getChapterShotsPath(projectId, record.id))
      return
    }
    if (state.key === 'prepare_shots') {
      navigate(getChapterStudioPath(projectId, record.id))
      return
    }
    void ensureHasShotsBeforeShooting({
      projectId,
      chapterId: record.id,
      storyboardCount: record.storyboardCount,
      navigate,
    })
  }

  const handleDivideAsync = async (record: Chapter) => {
    const scriptText = record.rawText?.trim()
    if (!scriptText) {
      message.warning('请先补章节原文')
      return
    }
    setChapterDivisionActionId(record.id)
    try {
      await executeAsyncTaskCreate({
        request: () =>
          ScriptProcessingService.divideScriptAsyncApiV1ScriptProcessingDivideAsyncPost({
            requestBody: {
              chapter_id: record.id,
              script_text: scriptText,
              write_to_db: true,
            },
          }),
        trackTaskData: (data) => {
          const tracked = createRelationTaskState(data)
          setChapterDivisionTaskMap(upsertRelationTaskStateInMap(chapterDivisionTaskMap, record.id, tracked))
          return tracked
        },
        startedMessage: taskCopy.startedMessage,
        reusedMessage: taskCopy.reusedMessage,
        fallbackErrorMessage: '启动分镜提取失败',
      })
    } catch {
      // executeAsyncTaskCreate 已统一处理错误提示
    } finally {
      setChapterDivisionActionId(null)
    }
  }

  const handleCancelDivideTask = async (record: Chapter) => {
    const activeTask = chapterDivisionTaskMap[record.id]
    if (!activeTask) return
    setChapterDivisionActionId(record.id)
    try {
      await executeTaskCancel({
        taskId: activeTask.taskId,
        reason: '用户在章节页取消分镜提取',
        applyCancelData: (data) => {
          if (!data?.task_id || !data?.status) return null
          const tracked = createRelationTaskState(
            {
              task_id: data.task_id,
              status: data.status,
            },
            { cancelRequested: data.cancel_requested ?? false },
          )
          setChapterDivisionTaskMap(upsertRelationTaskStateInMap(chapterDivisionTaskMap, record.id, tracked))
          return tracked
        },
        cancelledImmediatelyMessage: taskCopy.cancelledImmediatelyMessage,
        cancelRequestedMessage: taskCopy.cancelRequestedMessage,
        fallbackErrorMessage: '取消任务失败',
      })
    } catch {
      // executeTaskCancel 已统一处理错误提示
    } finally {
      setChapterDivisionActionId(null)
    }
  }

  useEffect(() => {
    const nextTaskIds: string[] = []

    chapters.forEach((chapter) => {
      const task = chapterDivisionTaskMap[chapter.id]
      if (!task) return
      nextTaskIds.push(task.taskId)
      taskUiUpsert({
        taskId: task.taskId,
        title: taskCopy.title,
        sourceLabel: chapter.title ? `章节：${chapter.title}` : '项目工作台章节列表',
        status: task.status,
        progress: task.progress,
        cancelRequested: task.cancelRequested,
        startedAtTs: task.startedAtTs,
        finishedAtTs: task.finishedAtTs,
        elapsedMs: task.elapsedMs,
        onCancel: () => void handleCancelDivideTask(chapter),
        onNavigate: projectId ? () => navigate(getChapterShotsPath(projectId, chapter.id)) : null,
      })
    })

    syncedTaskIdsRef.current
      .filter((taskId) => !nextTaskIds.includes(taskId))
      .forEach((taskId) => taskUiRemove(taskId))

    syncedTaskIdsRef.current = nextTaskIds
  }, [chapterDivisionTaskMap, chapters, handleCancelDivideTask, navigate, projectId, taskCopy.title, taskUiRemove, taskUiUpsert])

  useEffect(() => {
    return () => {
      syncedTaskIdsRef.current.forEach((taskId) => taskUiRemove(taskId))
      syncedTaskIdsRef.current = []
    }
  }, [taskUiRemove])

  /**
   * 章节级「一键配音」：为本章所有镜头下「尚未配音」的台词依次生成配音。
   *
   * 说明：
   * - 逐镜头拉 preparation-state 拿台词列表，再逐条创建 TTS 任务并轮询；
   * - 串行执行（TTS 在 Celery 侧并发受限，且串行便于定位是哪个角色缺音色）；
   * - 配音产物之后会自动作为参考音频进入该镜头的视频生成（≤3 条）。
   */
  const generateChapterAudio = async (record: Chapter) => {
    if (!projectId || chapterAudioRunningId) return
    setChapterAudioRunningId(record.id)
    const hide = message.loading('正在读取本章台词…', 0)
    let ok = 0
    const failures: string[] = []
    try {
      // 1. 拉本章所有镜头
      const shotsResp = await StudioShotsService.listShotsApiV1StudioShotsGet({
        chapterId: record.id,
        page: 1,
        pageSize: 100,
      })
      const shots = ((shotsResp.data as { items?: Array<{ id: string }> } | undefined)?.items ?? []) as Array<{
        id: string
      }>
      hide()
      if (shots.length === 0) {
        message.info('本章还没有分镜，请先提取分镜')
        return
      }

      const progress = message.loading(`共 ${shots.length} 个镜头，开始生成配音…`, 0)
      for (const shot of shots) {
        // 2. 取该镜头的台词
        let lines: Array<{ id: number; index: number; generated_audio_file_id?: string | null }> = []
        try {
          const stateResp =
            await StudioShotsService.getShotPreparationStateApiApiV1StudioShotsShotIdPreparationStateGet({
              shotId: shot.id,
            })
          lines = ((stateResp.data as { saved_dialogue_lines?: unknown[] } | undefined)?.saved_dialogue_lines ??
            []) as typeof lines
        } catch {
          continue
        }
        const pending = lines.filter((l) => !l.generated_audio_file_id)
        for (const line of pending) {
          try {
            await runSpeechTaskForLine(line.id)
            ok += 1
          } catch (error) {
            failures.push(`镜头${shot.id.slice(0, 6)} 第${line.index + 1}句: ${
              error instanceof Error ? error.message : String(error)
            }`)
          }
        }
      }
      progress()

      if (failures.length === 0) {
        message.success(ok > 0 ? `已生成 ${ok} 条配音` : '本章所有台词都已有配音')
      } else {
        message.warning(`成功 ${ok} 条，失败 ${failures.length} 条（前 3 条：${failures.slice(0, 3).join('；')}）`)
      }
      void refresh()
    } catch (error) {
      hide()
      message.error(error instanceof Error ? error.message : '一键配音失败')
    } finally {
      setChapterAudioRunningId(null)
    }
  }

  const buildActionMenuItems = (record: Chapter): MenuProps['items'] => {
    if (!projectId) return []
    const state = getChapterPreparationState(record)
    const activeTask = chapterDivisionTaskMap[record.id]
    return [
      {
        key: 'prepare',
        label: '一键准备（拆分镜 → 建资产）',
        icon: <ThunderboltOutlined />,
        onClick: () => setPrepareChapter(record),
      },
      {
        key: 'shots',
        label: '查看分镜',
        icon: <ScissorOutlined />,
        onClick: () => navigate(getChapterShotsPath(projectId, record.id)),
      },
      (record.storyboardCount ?? 0) > 0
        ? {
            key: 'board',
            label: '镜头看板（按状态分列）',
            icon: <AppstoreOutlined />,
            onClick: () => navigate(getChapterBoardPath(projectId, record.id)),
          }
        : null,
      (chapterFlowMap[record.id]?.pendingConfirmShots ?? 0) > 0
        ? {
            key: 'batch-confirm',
            label: `批量确认（${chapterFlowMap[record.id]?.pendingConfirmShots} 个待确认）`,
            icon: <CheckSquareOutlined />,
            onClick: () =>
              navigate(`${getChapterBoardPath(projectId, record.id)}?batch=confirm`),
          }
        : null,
      (record.storyboardCount ?? 0) > 0
        ? {
            key: 'review',
            label: '检查流程（参考图 → 分镜 → 对话）',
            icon: <CheckSquareOutlined />,
            onClick: () => navigate(getChapterReviewPath(projectId, record.id)),
          }
        : null,
      state.key !== 'prepare_shots' && (record.storyboardCount ?? 0) > 0
        ? {
            key: 'studio',
            label: '进入工作室',
            icon: <FileSearchOutlined />,
            onClick: () => navigate(getChapterStudioPath(projectId, record.id)),
          }
        : null,
      {
        key: 'raw',
        label: '编辑原文',
        icon: <EditOutlined />,
        onClick: () => openEditModal(record),
      },
      (record.storyboardCount ?? 0) > 0
        ? {
            key: 'audio',
            label:
              chapterAudioRunningId === record.id ? '配音生成中…' : '一键配音（本章全部台词）',
            icon: <SoundOutlined />,
            disabled: chapterAudioRunningId !== null,
            onClick: () => void generateChapterAudio(record),
          }
        : null,
      activeTask
        ? {
            key: 'cancel_divide',
            label: activeTask.cancelRequested ? '取消请求已发出' : '取消分镜提取',
            icon: <StopOutlined />,
            disabled: activeTask.cancelRequested || chapterDivisionActionId === record.id,
            onClick: () => void handleCancelDivideTask(record),
          }
        : null,
    ].filter(Boolean)
  }

  const columns: TableColumnsType<Chapter> = [
    { title: '章节', dataIndex: 'index', key: 'index', width: 80, render: (v: number) => `第${v}集` },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 240,
      ellipsis: true,
      render: (title: string, record) => (
        <Button
          type="link"
          size="small"
          style={{ paddingInline: 0 }}
          onClick={() => openEditModal(record)}
        >
          {title || '未命名章节'}
        </Button>
      ),
    },
    { title: '分镜数', dataIndex: 'storyboardCount', key: 'storyboardCount', width: 90 },
    {
      title: '准备状态',
      key: 'preparation',
      width: 160,
      render: (_, record) => {
        const activeTask = chapterDivisionTaskMap[record.id]
        if (activeTask) {
          return (
            <div className="space-y-1">
              <Tag color={activeTask.cancelRequested ? 'orange' : 'processing'}>
                {activeTask.cancelRequested ? '正在取消提取' : '分镜提取中'}
              </Tag>
              <div className="text-[11px] text-gray-500 leading-5">
                {activeTask.cancelRequested ? '已请求取消，将在当前步骤结束后停止' : '系统正在异步提取当前章节分镜'}
              </div>
            </div>
          )
        }
        const state = getChapterPreparationState(record)
        return (
          <div className="space-y-1">
            <Tag color={state.color}>{state.text}</Tag>
            <div className="text-[11px] text-gray-500 leading-5">{state.hint}</div>
          </div>
        )
      },
    },
    {
      title: '分镜流转',
      key: 'shotFlow',
      width: 190,
      render: (_, record) => {
        const stats = chapterFlowMap[record.id]
        const pendingCount = stats?.pendingConfirmShots ?? 0
        return (
          <div className="flex flex-wrap gap-1">
            {/* 「待确认 N」本身就是入口：点它直达看板并自动打开批量确认 */}
            {pendingCount > 0 ? (
              <Tooltip title="打开镜头看板并批量确认这一章待确认的镜头">
                <Tag
                  bordered={false}
                  color="gold"
                  role="button"
                  tabIndex={0}
                  className="mr-0 cursor-pointer"
                  onClick={() =>
                    projectId && navigate(`${getChapterBoardPath(projectId, record.id)}?batch=confirm`)
                  }
                  onKeyDown={(event) => {
                    if ((event.key === 'Enter' || event.key === ' ') && projectId) {
                      event.preventDefault()
                      navigate(`${getChapterBoardPath(projectId, record.id)}?batch=confirm`)
                    }
                  }}
                >
                  待确认 {pendingCount} →
                </Tag>
              </Tooltip>
            ) : (
              <Tag bordered={false} color="gold" className="mr-0">
                待确认 0
              </Tag>
            )}
            <Tag bordered={false} color="green" className="mr-0">
              已就绪 {stats?.readyShots ?? 0}
            </Tag>
            <Tag bordered={false} color="processing" className="mr-0">
              生成中 {stats?.generatingShots ?? 0}
            </Tag>
          </div>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: Chapter['status']) => (
        <Tag color={chapterStatusMap[status].color}>{chapterStatusMap[status].text}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 205,
      render: (_, record) => {
        const state = getChapterPreparationState(record)
        const activeTask = chapterDivisionTaskMap[record.id]
        const primaryIcon = activeTask
          ? activeTask.cancelRequested
            ? <SyncOutlined spin />
            : <LoadingOutlined />
          : state.primaryIcon
        const primaryText = activeTask
          ? activeTask.cancelRequested
            ? '查看取消进度'
            : '查看提取进度'
          : state.primaryAction
        const primaryLoading = chapterDivisionActionId === record.id && state.key === 'extract_shots' && !activeTask

        return (
          <Space size={8}>
            <Button
              type="primary"
              size="small"
              onClick={() => {
                if (state.key === 'extract_shots' && !activeTask) {
                  void handleDivideAsync(record)
                  return
                }
                handlePrimaryAction(record)
              }}
              style={{ minWidth: 112, justifyContent: 'center' }}
              icon={primaryIcon}
              loading={primaryLoading}
            >
              {primaryText}
            </Button>
            {/* 一行只保留「主动作 + 看板 + 更多」：一键准备/检查流程/配音等低频操作收进菜单，
                避免每行 5 个控件把表格挤到横向溢出 */}
            {(record.storyboardCount ?? 0) > 0 ? (
              <Tooltip title="镜头看板：按「待确认 / 生成中 / 已就绪」查看">
                <Button
                  size="small"
                  icon={<AppstoreOutlined />}
                  aria-label="镜头看板"
                  onClick={() => navigate(getChapterBoardPath(projectId!, record.id))}
                />
              </Tooltip>
            ) : null}
            <Dropdown
              trigger={['click']}
              menu={{ items: buildActionMenuItems(record) }}
            >
              <Button
                size="small"
                icon={<MoreOutlined />}
                aria-label="更多操作"
                loading={chapterDivisionActionId === record.id && !!activeTask}
              />
            </Dropdown>
          </Space>
        )
      },
    },
  ]

  if (chapters.length === 0 && !loading) {
    return (
      <>
        <Card>
          <Empty description="还没有任何章节，立即创建第一章吧" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Space>
            <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建第一章
            </Button>
          </Space>
        </Empty>
        </Card>
        <Modal
          title="新建章节"
          open={createOpen}
          onCancel={() => setCreateOpen(false)}
          onOk={useMock ? handleCreateChapterMock : handleCreateChapter}
          okText="创建"
          width={560}
        >
          <div className="space-y-3">
            <div>
              <span className="text-gray-600 text-sm">章节标题</span>
              <Input
                placeholder="例如：第1集 出租屋里的争吵"
                value={createTitle}
                onChange={(e) => setCreateTitle(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <span className="text-gray-600 text-sm">章节内容（可粘贴剧本）</span>
              <TextArea
                rows={6}
                placeholder="粘贴文学剧本..."
                value={createContent}
                onChange={(e) => setCreateContent(e.target.value)}
                className="mt-1 font-mono text-sm"
              />
            </div>
          </div>
        </Modal>
      </>
    )
  }

  return (
    <Card
      title="章节列表"
      extra={
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建章节
          </Button>
        </Space>
      }
    >
      <Table<Chapter>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={chapters}
        pagination={{ pageSize: 10 }}
        size="small"
        scroll={{ x: 1150 }}
      />

      <ChapterRawTextEditorModal
        open={editOpen}
        onClose={() => {
          setEditOpen(false)
          setEditingChapter(null)
        }}
        chapterId={editingChapter?.id}
        onSaved={(next) => {
          if (editingChapter?.id && typeof next.rawText === 'string') {
            patchChapterLocal(editingChapter.id, { rawText: next.rawText })
          }
          void refresh()
        }}
      />

      <ChapterPrepareWizard
        open={prepareChapter !== null}
        projectId={projectId ?? ''}
        chapterId={prepareChapter?.id ?? ''}
        chapterIndex={prepareChapter?.index ?? 0}
        chapterTitle={prepareChapter?.title ?? ''}
        storyboardCount={prepareChapter?.storyboardCount ?? 0}
        rawText={prepareChapter?.rawText ?? ''}
        onClose={() => setPrepareChapter(null)}
        onFinished={() => {
          void refresh()
        }}
      />

      <Modal
        title="新建章节"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={useMock ? handleCreateChapterMock : handleCreateChapter}
        okText="创建"
        width={560}
      >
        <div className="space-y-3">
          <div>
            <span className="text-gray-600 text-sm">章节标题</span>
            <Input
              placeholder="例如：第1集 出租屋里的争吵"
              value={createTitle}
              onChange={(e) => setCreateTitle(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <span className="text-gray-600 text-sm">章节内容（可粘贴剧本）</span>
            <TextArea
              rows={6}
              placeholder="粘贴文学剧本..."
              value={createContent}
              onChange={(e) => setCreateContent(e.target.value)}
              className="mt-1 font-mono text-sm"
            />
          </div>
        </div>
      </Modal>
    </Card>
  )
}
