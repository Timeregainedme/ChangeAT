/**
 * 项目设置页。
 *
 * 职责边界（与 AGENTS.md 的页面职责约定一致）：
 * - 本页只放「项目级」配置，不放需要逐镜头/逐资产操作的业务参数。
 * - 目前承载：
 *   1. 视频生成是否自动带上台词配音作为参考音频；
 *   2. 图片清晰度（1K / 2K，对应 standard / high）；
 *   3. 视频分辨率（480p / 768p / 1080p / 2k / 4k，由供应商能力决定）。
 *
 * 交互取舍：
 * - 每项改动立即 PATCH 保存并提示，避免「改了忘记点保存」；
 * - 保存失败回滚本地状态，避免 UI 与后端不一致；
 * - 可选项全部来自后端能力接口（image/video generation options），
 *   不在前端写死枚举——否则换模型后会出现「界面上有、供应商其实不支持」。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Card, Descriptions, Divider, Select, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { SoundOutlined } from '@ant-design/icons'
import { LlmService, StudioProjectsService } from '../../../../../services/generated'
import type {
  ImageGenerationOptionsRead,
  ProjectRead,
  VideoGenerationOptionsRead,
} from '../../../../../services/generated'

const { Text } = Typography

/** 图片分辨率档位的中文名：后端只给 standard/high，界面必须说人话。 */
const IMAGE_PROFILE_LABEL: Record<string, string> = {
  standard: '标准（1K）',
  high: '高清（2K）',
}

/** 视频分辨率档位的展示名：768p / 2k 这类值直接大写更易读。 */
function formatVideoResolution(value: string): string {
  return value.toUpperCase()
}

export function SettingsTab({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<ProjectRead | null>(null)
  const [imageOptions, setImageOptions] = useState<ImageGenerationOptionsRead | null>(null)
  const [videoOptions, setVideoOptions] = useState<VideoGenerationOptionsRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  /** 拉取项目详情与两个能力接口（项目设置的可选项都来自后者）。 */
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [projectResp, imageResp, videoResp] = await Promise.all([
        StudioProjectsService.getProjectApiV1StudioProjectsProjectIdGet({ projectId }),
        LlmService.getImageGenerationOptionsApiV1LlmImageGenerationOptionsGet().catch(() => null),
        LlmService.getVideoGenerationOptionsApiV1LlmVideoGenerationOptionsGet().catch(() => null),
      ])
      setProject((projectResp.data as ProjectRead | undefined) ?? null)
      setImageOptions((imageResp?.data as ImageGenerationOptionsRead | undefined) ?? null)
      setVideoOptions((videoResp?.data as VideoGenerationOptionsRead | undefined) ?? null)
    } catch (error) {
      message.error(error instanceof Error ? `加载项目设置失败：${error.message}` : '加载项目设置失败')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * 统一的保存入口。
   *
   * 所有设置项都是「立即生效」的开关或下拉，共用一个保存流程：
   * 先乐观更新、失败回滚、最后提示。避免每个项各写一份 try/catch。
   */
  const patchProject = useCallback(
    async (patch: Record<string, string | boolean | null>, successText: string, revert: () => void) => {
      if (saving) return
      setSaving(true)
      try {
        await StudioProjectsService.updateProjectApiV1StudioProjectsProjectIdPatch({
          projectId,
          requestBody: patch as never,
        })
        message.success(successText)
      } catch (error) {
        revert()
        message.error(error instanceof Error ? `保存失败：${error.message}` : '保存失败，已回滚')
      } finally {
        setSaving(false)
      }
    },
    [projectId, saving],
  )

  /** 切换「使用台词配音作为参考音频」。 */
  const toggleDialogAudio = useCallback(
    (checked: boolean) => {
      if (!project) return
      const previous = project.use_dialog_audio_as_reference ?? true
      setProject({ ...project, use_dialog_audio_as_reference: checked })
      void patchProject(
        { use_dialog_audio_as_reference: checked },
        checked ? '已开启：视频生成会带上台词配音' : '已关闭：视频生成只用参考图',
        () => setProject((prev) => (prev ? { ...prev, use_dialog_audio_as_reference: previous } : prev)),
      )
    },
    [patchProject, project],
  )

  /** 修改图片清晰度。 */
  const changeImageProfile = useCallback(
    (value: string) => {
      if (!project) return
      const previous = project.default_image_resolution_profile ?? null
      setProject({ ...project, default_image_resolution_profile: value })
      void patchProject(
        { default_image_resolution_profile: value },
        `图片清晰度已设为 ${IMAGE_PROFILE_LABEL[value] ?? value}`,
        () => setProject((prev) => (prev ? { ...prev, default_image_resolution_profile: previous } : prev)),
      )
    },
    [patchProject, project],
  )

  /** 修改视频分辨率。 */
  const changeVideoResolution = useCallback(
    (value: string) => {
      if (!project) return
      const previous = project.default_video_resolution ?? null
      setProject({ ...project, default_video_resolution: value })
      void patchProject(
        { default_video_resolution: value },
        `视频分辨率已设为 ${formatVideoResolution(value)}`,
        () => setProject((prev) => (prev ? { ...prev, default_video_resolution: previous } : prev)),
      )
    },
    [patchProject, project],
  )

  /** 图片档位可选项：从 ratio_size_profiles 的键里取，保持与后端一致。 */
  const imageProfileOptions = useMemo(() => {
    const profiles = imageOptions?.ratio_size_profiles
    const firstRatio = profiles ? Object.values(profiles)[0] : undefined
    const keys = firstRatio ? Object.keys(firstRatio) : ['standard', 'high']
    return keys.map((key) => ({
      value: key,
      label: IMAGE_PROFILE_LABEL[key] ?? key,
    }))
  }, [imageOptions])

  if (loading) {
    return (
      <div className="py-12 text-center">
        <Spin tip="加载项目设置…" />
      </div>
    )
  }

  if (!project) {
    return <Alert type="warning" showIcon message="未找到项目，请返回项目列表重新进入" />
  }

  const audioEnabled = project.use_dialog_audio_as_reference ?? true
  const imageProfile = project.default_image_resolution_profile ?? imageOptions?.default_resolution_profile ?? ''
  const videoResolution = project.default_video_resolution ?? videoOptions?.default_resolution ?? ''
  const videoResolutionOptions = videoOptions?.allowed_resolutions ?? []

  /** 当前比例下，各档位对应的像素尺寸，用于在选项里给出直观参考。 */
  const ratioSizeHint = (() => {
    const ratio = project.default_video_ratio
    const profiles = imageOptions?.ratio_size_profiles
    if (!ratio || !profiles?.[ratio]) return null
    return profiles[ratio]
  })()

  return (
    <div className="space-y-4">
      <Card title="项目信息" size="small">
        <Descriptions size="small" column={2} bordered>
          <Descriptions.Item label="项目名称">{project.name}</Descriptions.Item>
          <Descriptions.Item label="题材/风格">{project.style}</Descriptions.Item>
          <Descriptions.Item label="画面表现形式">{project.visual_style}</Descriptions.Item>
          <Descriptions.Item label="默认视频比例">
            {project.default_video_ratio || <Text type="secondary">未设置</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="图片清晰度">
            {project.default_image_resolution_profile ? (
              <Tag color="blue">
                {IMAGE_PROFILE_LABEL[project.default_image_resolution_profile] ??
                  project.default_image_resolution_profile}
              </Tag>
            ) : (
              <Text type="secondary">跟随模型默认</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="视频分辨率">
            {project.default_video_resolution ? (
              <Tag color="blue">{formatVideoResolution(project.default_video_resolution)}</Tag>
            ) : (
              <Text type="secondary">跟随模型默认</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="项目 ID" span={2}>
            <Text type="secondary" copyable>
              {project.id}
            </Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="图片生成" size="small">
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <Text strong>关键帧清晰度</Text>
              <div className="text-xs text-gray-500 mt-1">
                影响本项目中所有关键帧、参考图的生成分辨率。1K 更快更省，2K 细节更足但更慢、更贵。
              </div>
            </div>
            <Select
              style={{ width: 200 }}
              value={imageProfile || undefined}
              loading={saving}
              placeholder="跟随模型默认"
              options={imageProfileOptions}
              onChange={(value) => changeImageProfile(value)}
            />
          </div>

          {ratioSizeHint ? (
            <div className="text-xs text-gray-500">
              当前比例 {project.default_video_ratio}：
              {Object.entries(ratioSizeHint).map(([key, size]) => (
                <span key={key} className="ml-2">
                  {IMAGE_PROFILE_LABEL[key] ?? key} = {size}
                </span>
              ))}
            </div>
          ) : null}

          {imageOptions?.model_name ? (
            <div className="text-xs text-gray-500">当前图片模型：{imageOptions.model_name}</div>
          ) : null}
        </Space>
      </Card>

      <Card title="视频生成" size="small">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <Text strong>视频分辨率</Text>
              <div className="text-xs text-gray-500 mt-1">
                生成镜头视频时下发给供应商的分辨率档位。可选值由当前视频模型决定；
                越高越清晰，也越慢、越占存储。
              </div>
            </div>
            <Select
              style={{ width: 200 }}
              value={videoResolution || undefined}
              loading={saving}
              placeholder="跟随模型默认"
              options={videoResolutionOptions.map((value) => ({
                value,
                label:
                  value === videoOptions?.default_resolution
                    ? `${formatVideoResolution(value)}（模型默认）`
                    : formatVideoResolution(value),
              }))}
              onChange={(value) => changeVideoResolution(value)}
              disabled={videoResolutionOptions.length === 0}
            />
          </div>

          {videoResolutionOptions.length === 0 ? (
            <div className="text-xs text-gray-500">
              当前视频模型不暴露分辨率参数，将使用供应商默认值。
            </div>
          ) : null}

          <Divider style={{ margin: '4px 0' }} />

          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <SoundOutlined />
                <Text strong>使用台词配音作为参考音频</Text>
                <Tag color={audioEnabled ? 'green' : 'default'}>
                  {audioEnabled ? '已开启' : '已关闭'}
                </Tag>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                开启后，生成镜头视频时会把该镜头下已配好的台词音频（最多 3 条）作为
                `reference_audio` 一起提交，用于对齐音色与说话节奏。
                关闭后视频只使用参考图，音频不参与生成。
              </div>
            </div>
            <Switch
              checked={audioEnabled}
              loading={saving}
              onChange={(checked) => toggleDialogAudio(checked)}
              checkedChildren="开启"
              unCheckedChildren="关闭"
            />
          </div>

          <Alert
            type="info"
            showIcon
            message="前置条件"
            description={
              <div className="text-xs leading-6">
                <div>· 参考音频不能单独使用：必须同时存在参考图（参考图模式下默认已满足）。</div>
                <div>· 每条音频需为 WAV/MP3、2–15 秒；台词配音默认输出的 WAV 已满足。</div>
                <div>· 说话角色未配置音色时，配音会返回 422，请先在角色/演员上选择音色。</div>
              </div>
            }
          />
        </Space>
      </Card>
    </div>
  )
}

export default SettingsTab
