/**
 * 项目设置页。
 *
 * 职责边界（与 AGENTS.md 的页面职责约定一致）：
 * - 本页只放「项目级」配置，不放需要逐镜头/逐资产操作的业务参数。
 * - 目前承载的开关：
 *   1. 视频生成是否自动带上台词配音作为参考音频
 *      （MiniMax H3 的 reference_audio；关掉后视频只用参考图，音频不参与）
 *
 * 交互取舍：
 * - 开关切换后立即 PATCH 保存并提示，避免「改了忘记点保存」这类常见困惑。
 * - 只读信息（项目 ID / 题材）单独展示，避免和可编辑项混淆。
 */
import { useCallback, useEffect, useState } from 'react'
import { Alert, Card, Descriptions, Divider, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { SoundOutlined } from '@ant-design/icons'
import { StudioProjectsService } from '../../../../../services/generated'
import type { ProjectRead } from '../../../../../services/generated'

const { Text } = Typography

export function SettingsTab({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<ProjectRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  /** 拉取项目详情（含项目级开关）。 */
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await StudioProjectsService.getProjectApiV1StudioProjectsProjectIdGet({
        projectId,
      })
      setProject((resp.data as ProjectRead | undefined) ?? null)
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
   * 切换「使用台词配音作为参考音频」。
   *
   * 立即保存：这是低风险、可随时回退的开关，没必要走「编辑-保存」两步。
   * 保存失败时回滚本地状态，避免 UI 与后端不一致。
   */
  const toggleDialogAudio = useCallback(
    async (checked: boolean) => {
      if (!project || saving) return
      const previous = project.use_dialog_audio_as_reference ?? true
      setProject({ ...project, use_dialog_audio_as_reference: checked })
      setSaving(true)
      try {
        await StudioProjectsService.updateProjectApiV1StudioProjectsProjectIdPatch({
          projectId,
          requestBody: { use_dialog_audio_as_reference: checked },
        })
        message.success(checked ? '已开启：视频生成会带上台词配音' : '已关闭：视频生成只用参考图')
      } catch (error) {
        setProject({ ...project, use_dialog_audio_as_reference: previous })
        message.error(
          error instanceof Error ? `保存失败：${error.message}` : '保存失败，已回滚',
        )
      } finally {
        setSaving(false)
      }
    },
    [project, projectId, saving],
  )

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
          <Descriptions.Item label="项目 ID" span={2}>
            <Text type="secondary" copyable>
              {project.id}
            </Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="视频生成" size="small">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
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
              onChange={(checked) => void toggleDialogAudio(checked)}
              checkedChildren="开启"
              unCheckedChildren="关闭"
            />
          </div>

          <Divider style={{ margin: '4px 0' }} />

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