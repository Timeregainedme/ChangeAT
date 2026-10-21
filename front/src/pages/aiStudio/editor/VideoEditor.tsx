import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Tooltip,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ExportOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
  WarningOutlined,
  SoundOutlined,
  PictureOutlined,
} from '@ant-design/icons'
import { Link, useParams } from 'react-router-dom'
import { StudioTimelineService } from '../../../services/generated'
import type { ProjectTimelineRead, TimelineClipRead, TimelineExportRead } from '../../../services/generated'
import { buildFileDownloadUrl } from '../assets/utils'
import { getStoredToken } from '../../../store/useAuthStore'

/** 后端 ValueError/HTTPException 统一返回 {code, message, data, meta}，detail 可能是字符串或数组。 */
function extractErrorMessage(error: unknown, fallback: string): string {
  const body = (error as { body?: unknown })?.body
  if (!body) {
    const text = (error as { message?: string })?.message
    return text || fallback
  }
  const record = body as Record<string, unknown>
  const detail = record.detail ?? record.message
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item
        const entry = item as Record<string, unknown>
        return typeof entry?.msg === 'string' ? entry.msg : JSON.stringify(item)
      })
      .filter(Boolean)
    if (parts.length > 0) return parts.join('；')
  }
  return fallback
}

function formatSeconds(value?: number | null): string {
  const total = Math.max(0, Math.round(value ?? 0))
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m}分${String(s).padStart(2, '0')}秒` : `${s}秒`
}

function formatRange(start?: number | null, end?: number | null): string {
  const from = Math.max(0, Math.round(start ?? 0))
  const to = Math.max(0, Math.round(end ?? 0))
  return `${from}s – ${to}s`
}

const FRAME_LABELS: Record<string, string> = {
  first: '首帧',
  last: '尾帧',
  key: '关键帧',
}

const VideoEditor = () => {
  const { projectId } = useParams<{ projectId: string }>()

  const [timeline, setTimeline] = useState<ProjectTimelineRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const [exported, setExported] = useState<TimelineExportRead | null>(null)
  const [preview, setPreview] = useState<TimelineClipRead | null>(null)

  const load = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const res = await StudioTimelineService.getProjectTimelineApiApiV1StudioTimelineProjectsProjectIdGet({
        projectId,
      })
      setTimeline(res?.data ?? null)
    } catch (err) {
      const msg = extractErrorMessage(err, '加载时间线失败')
      setError(msg)
      setTimeline(null)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  const clips = useMemo(() => timeline?.clips ?? [], [timeline])

  const handleExport = useCallback(async () => {
    if (!projectId) return
    setExporting(true)
    try {
      const res = await StudioTimelineService.exportProjectTimelineApiApiV1StudioTimelineProjectsProjectIdExportPost({
        projectId,
      })
      const result = res?.data ?? null
      setExported(result)
      if (result) {
        message.success(`导出完成：${result.name}（${formatSeconds(result.duration)}）`)
      }
    } catch (err) {
      message.error(extractErrorMessage(err, '导出成片失败'))
    } finally {
      setExporting(false)
    }
  }, [projectId])

  /**
   * 一键打包下载全部片段视频。
   *
   * 走后端的 zip 接口而不是前端打包：视频体积大，前端逐个下载再压缩既慢又占内存。
   * 这里用 fetch + blob 触发下载，因为下载接口需要 Authorization 头（不能用裸链）。
   */
  const handleExportArchive = useCallback(async () => {
    if (!projectId) return
    setArchiving(true)
    try {
      const res = await fetch(`/api/v1/studio/timeline/projects/${projectId}/clips-archive`, {
        headers: { Authorization: `Bearer ${getStoredToken() ?? ''}` },
      })
      if (!res.ok) {
        let detail = '打包导出失败'
        try {
          const body = (await res.json()) as { detail?: string; message?: string }
          detail = body.detail || body.message || detail
        } catch {
          // 非 JSON 响应（如网关错误页）时保留默认文案
        }
        throw new Error(detail)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${timeline?.project_name || projectId}-片段打包.zip`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      // 立即 revoke 会让部分浏览器在下载真正开始前就失去数据源（表现为 0 字节失败），
      // 延迟回收，代价只是一个短期内存引用。
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      message.success('片段打包已开始下载')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '打包导出失败')
    } finally {
      setArchiving(false)
    }
  }, [projectId, timeline?.project_name])

  const stats = timeline?.stats
  const exportable = Boolean(stats?.exportable)
  const archivable = (stats?.clips_with_video ?? 0) > 0

  return (
    <div className="h-full overflow-auto p-4">
      <div className="mb-3">
        <Link
          to={projectId ? `/projects/${projectId}` : '/projects'}
          className="text-sm text-gray-600 hover:text-blue-600 inline-flex items-center gap-1"
        >
          <ArrowLeftOutlined /> {projectId ? '返回项目工作台' : '项目列表'}
        </Link>
      </div>

      <Card
        title={
          <Space>
            <VideoCameraOutlined />
            <span>时间线与成片导出</span>
            {timeline?.project_name ? (
              <span className="text-sm font-normal text-gray-500">{timeline.project_name}</span>
            ) : null}
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} disabled={loading}>
              刷新
            </Button>
            <Tooltip
              title={
                archivable
                  ? '把每个已生成的片段视频原样打包成一个 zip（未生成的会写进 MANIFEST）'
                  : '还没有任何片段生成视频，无法打包'
              }
            >
              <Button
                icon={<DownloadOutlined />}
                loading={archiving}
                disabled={!archivable || loading}
                onClick={() => void handleExportArchive()}
              >
                导出片段压缩包
              </Button>
            </Tooltip>
            <Tooltip
              title={
                exportable
                  ? '把全部镜头视频按顺序拼接导出成一个 mp4 文件'
                  : '还有镜头没有生成视频，暂时无法导出'
              }
            >
              <Button
                type="primary"
                icon={<ExportOutlined />}
                loading={exporting}
                disabled={!exportable || loading}
                onClick={() => void handleExport()}
              >
                导出成片
              </Button>
            </Tooltip>
          </Space>
        }
      >
        {loading ? (
          <div className="py-16 text-center">
            <Spin tip="正在加载时间线…" />
          </div>
        ) : error ? (
          <Alert
            type="error"
            showIcon
            message="无法加载时间线"
            description={error}
            action={
              <Button size="small" onClick={() => void load()}>
                重试
              </Button>
            }
          />
        ) : (
          <>
            {exported ? (
              <Alert
                className="mb-4"
                type="success"
                showIcon
                message={`已导出成片：${exported.name}`}
                description={`共 ${exported.clip_count} 个片段，时长 ${formatSeconds(exported.duration)}。`}
                action={
                  <Button
                    size="small"
                    type="primary"
                    icon={<DownloadOutlined />}
                    onClick={() => {
                      const url = exported.file_id ? buildFileDownloadUrl(exported.file_id) : undefined
                      if (url) window.open(url, '_blank', 'noopener,noreferrer')
                    }}
                  >
                    下载
                  </Button>
                }
              />
            ) : null}

            <Row gutter={16} className="mb-4">
              <Col xs={12} md={6}>
                <Statistic title="分镜片段" value={stats?.clip_count ?? 0} suffix="个" />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="目标总时长" value={stats?.total_duration ?? 0} suffix="秒" />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="已生成视频"
                  value={stats?.clips_with_video ?? 0}
                  suffix={`/ ${stats?.clip_count ?? 0}`}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="带配音片段" value={stats?.clips_with_audio ?? 0} suffix="个" />
              </Col>
            </Row>

            {!exportable && (stats?.clip_count ?? 0) > 0 ? (
              <Alert
                className="mb-4"
                type="warning"
                showIcon
                icon={<WarningOutlined />}
                message={`还有 ${stats?.clips_missing_video ?? 0} 个分镜没有生成视频`}
                description="导出成片要求每个分镜都有视频；请先在分镜工作室里补齐视频生成。"
              />
            ) : null}

            {clips.length === 0 ? (
              <Empty description="该项目还没有分镜，先在项目工作台完成章节切分与分镜生成" />
            ) : (
              <div className="space-y-3">
                {clips.map((clip) => (
                  <Card
                    key={clip.shot_id}
                    size="small"
                    className="border border-gray-200"
                  >
                    <div className="flex gap-3">
                      <div className="w-40 shrink-0">
                        <div className="aspect-video bg-gray-100 rounded overflow-hidden flex items-center justify-center">
                          {clip.thumbnail ? (
                            <img
                              src={buildFileDownloadUrl(clip.thumbnail) ?? clip.thumbnail}
                              alt={clip.title}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <PictureOutlined className="text-gray-300 text-2xl" />
                          )}
                        </div>
                        <div className="mt-2 text-xs text-gray-500 text-center">
                          {formatRange(clip.start, clip.end)}
                        </div>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs text-gray-400">
                            第 {clip.chapter_index + 1} 章 · {clip.chapter_title}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center gap-2 flex-wrap">
                          <span className="font-medium">
                            #{clip.index + 1} {clip.title || '未命名分镜'}
                          </span>
                          <Tag>{clip.status}</Tag>
                          <Tag color="blue">{formatSeconds(clip.duration)}</Tag>
                          {clip.video_file_id ? (
                            <Tag color="green">视频已生成</Tag>
                          ) : (
                            <Tag color="red">缺视频</Tag>
                          )}
                          {clip.audio_file_id || (clip.dialogs ?? []).some((d) => d.audio_file_id) ? (
                            <Tag color="cyan" icon={<SoundOutlined />}>
                              有配音
                            </Tag>
                          ) : null}
                        </div>

                        <div className="mt-2 flex items-center gap-2 flex-wrap">
                          {(clip.frames ?? []).map((frame) => (
                            <Tag key={`${clip.shot_id}-${frame.frame_type}`} icon={<PictureOutlined />}>
                              {FRAME_LABELS[frame.frame_type] ?? frame.frame_type}
                              {frame.width && frame.height ? ` ${frame.width}×${frame.height}` : ''}
                            </Tag>
                          ))}
                          {(clip.dialogs ?? []).length > 0 ? (
                            <Tag>{`台词 ${(clip.dialogs ?? []).length} 条`}</Tag>
                          ) : null}
                        </div>

                        {(clip.dialogs ?? []).length > 0 ? (
                          <div className="mt-2 text-xs text-gray-500 line-clamp-2">
                            {(clip.dialogs ?? [])
                              .map((d) => `${d.speaker_name ? `${d.speaker_name}：` : ''}${d.text}`)
                              .join(' / ')}
                          </div>
                        ) : null}
                      </div>

                      <div className="shrink-0 flex items-center">
                        <Button
                          icon={<PlayCircleOutlined />}
                          disabled={!clip.video_file_id}
                          onClick={() => setPreview(clip)}
                        >
                          预览
                        </Button>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      <Modal
        title={preview ? `#${preview.index + 1} ${preview.title || '未命名分镜'}` : '分镜预览'}
        open={preview !== null}
        footer={null}
        width={720}
        destroyOnClose
        onCancel={() => setPreview(null)}
      >
        {preview?.video_file_id ? (
          <video
            className="w-full max-h-[70vh] bg-black rounded"
            src={buildFileDownloadUrl(preview.video_file_id)}
            controls
            playsInline
          >
            您的浏览器不支持视频播放
          </video>
        ) : (
          <Empty description="该分镜还没有生成视频" />
        )}
      </Modal>
    </div>
  )
}

export default VideoEditor
