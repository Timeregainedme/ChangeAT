/**
 * 检查流程 · 第三段「对话」。
 *
 * 目标：按镜头过一遍台词，能就地改文案/情绪、就地补配音或重抽配音，
 * 并清楚看到「有几句、几句配了音」。
 *
 * 行为边界：
 * - 只处理已保存的台词（saved_dialogue_lines）；候选台词仍需在分镜编辑页确认，
 *   避免检查页悄悄改变「提取确认」这一职责。
 * - 配音产物挂在台词上，随后会作为参考音频进入视频生成（受项目开关控制）。
 */
import { useState } from 'react'
import { Button, Card, Collapse, Empty, Input, Space, Tag, Tooltip, Typography, message } from 'antd'
import { ReloadOutlined, SoundOutlined } from '@ant-design/icons'
import { StudioShotDialogLinesService } from '../../../../services/generated'
import type { ShotDialogLineRead } from '../../../../services/generated'
import { buildFileDownloadUrl } from '../../assets/utils'
import { describeSpeechError, runSpeechTaskForLine } from '../../shots/tts'
import type { ShotBundle } from '../types'

const { Text } = Typography

type ReviewDialogueSectionProps = {
  bundles: ShotBundle[]
  /** 台词内容/配音变化后通知父级刷新 */
  onChanged: () => void
  onOpenShot: (shotId: string) => void
}

function dialogTitle(line: ShotDialogLineRead): string {
  if (line.speaker_name) return line.speaker_name
  if (line.line_mode === 'VOICE_OVER') return '旁白'
  return '未指定说话人'
}

export function ReviewDialogueSection({ bundles, onChanged, onOpenShot }: ReviewDialogueSectionProps) {
  /** 正在配音的台词行 id */
  const [generatingIds, setGeneratingIds] = useState<Record<number, boolean>>({})
  /** 镜头级批量配音进行中的镜头 id */
  const [batchShotId, setBatchShotId] = useState<string | null>(null)

  const shotBundles = bundles.map((bundle) => ({
    bundle,
    lines: [...(bundle.prep?.saved_dialogue_lines ?? [])].sort((a, b) => (a.index ?? 0) - (b.index ?? 0)),
  }))

  const totalLines = shotBundles.reduce((sum, item) => sum + item.lines.length, 0)
  const totalAudio = shotBundles.reduce(
    (sum, item) => sum + item.lines.filter((l) => l.generated_audio_file_id).length,
    0,
  )

  /** 单句配音（含重抽）。 */
  const generateOne = async (line: ShotDialogLineRead) => {
    if (generatingIds[line.id]) return
    setGeneratingIds((prev) => ({ ...prev, [line.id]: true }))
    try {
      await runSpeechTaskForLine(line.id)
      message.success(`#${(line.index ?? 0) + 1} 配音已生成`)
      onChanged()
    } catch (error) {
      message.error(describeSpeechError(error))
    } finally {
      setGeneratingIds((prev) => ({ ...prev, [line.id]: false }))
    }
  }

  /**
   * 镜头级批量配音：只处理还没有配音的台词，串行执行。
   *
   * 串行而非并发：TTS 在 Celery 侧并发有限（默认 2），
   * 串行还能在失败时准确指出是哪一句、哪个角色出的问题。
   */
  const generateShot = async (bundle: ShotBundle, lines: ShotDialogLineRead[]) => {
    if (batchShotId) return
    const pending = lines.filter((l) => !l.generated_audio_file_id)
    if (pending.length === 0) {
      message.info('该镜头所有台词都已有配音')
      return
    }
    setBatchShotId(bundle.shot.id)
    let ok = 0
    const failures: string[] = []
    try {
      for (const line of pending) {
        setGeneratingIds((prev) => ({ ...prev, [line.id]: true }))
        try {
          await runSpeechTaskForLine(line.id)
          ok += 1
        } catch (error) {
          failures.push(`#${(line.index ?? 0) + 1} ${describeSpeechError(error)}`)
        } finally {
          setGeneratingIds((prev) => ({ ...prev, [line.id]: false }))
        }
      }
      onChanged()
      if (failures.length === 0) {
        message.success(`已生成 ${ok} 条配音`)
      } else {
        message.warning(`成功 ${ok} 条，失败 ${failures.length} 条：${failures.slice(0, 3).join('；')}`)
      }
    } finally {
      setBatchShotId(null)
    }
  }

  if (totalLines === 0) {
    return <Empty description="本章还没有已确认的台词（可先在分镜编辑页确认对白候选）" />
  }

  return (
    <div className="space-y-3">
      <Card size="small">
        <Space size={8} wrap>
          <Tag color="blue">台词 {totalLines} 句</Tag>
          <Tag color={totalAudio === totalLines ? 'green' : 'orange'}>已配音 {totalAudio} 句</Tag>
          <Text type="secondary" className="text-xs">
            配音产物会自动挂到台词上；生成视频时（项目开关开启）会作为参考音频提交。
          </Text>
        </Space>
      </Card>

      <Collapse
        defaultActiveKey={shotBundles.filter((item) => item.lines.length > 0).map((item) => item.bundle.shot.id)}
        items={shotBundles
          .filter((item) => item.lines.length > 0)
          .map(({ bundle, lines }) => {
            const audioCount = lines.filter((l) => l.generated_audio_file_id).length
            return {
              key: bundle.shot.id,
              label: (
                <Space size={8} wrap>
                  <Tag color="blue">#{bundle.shot.index + 1}</Tag>
                  <span className="font-medium">{bundle.shot.title || '未命名镜头'}</span>
                  <Tag color={audioCount === lines.length ? 'green' : 'orange'}>
                    配音 {audioCount} / {lines.length}
                  </Tag>
                </Space>
              ),
              extra: (
                <Space size={4} onClick={(e) => e.stopPropagation()}>
                  <Button
                    size="small"
                    icon={<SoundOutlined />}
                    loading={batchShotId === bundle.shot.id}
                    disabled={audioCount === lines.length || batchShotId !== null}
                    onClick={() => void generateShot(bundle, lines)}
                  >
                    补配音
                  </Button>
                  <Button size="small" type="link" onClick={() => onOpenShot(bundle.shot.id)}>
                    编辑镜头
                  </Button>
                </Space>
              ),
              children: (
                <div className="space-y-2">
                  {lines.map((line) => (
                    <DialogueRow
                      key={line.id}
                      line={line}
                      generating={!!generatingIds[line.id]}
                      onGenerate={() => void generateOne(line)}
                      onSaved={onChanged}
                    />
                  ))}
                </div>
              ),
            }
          })}
      />
    </div>
  )
}

/**
 * 单条台词行：文案 + 情绪可改，配音可播可重抽。
 *
 * 提交时机：输入框失焦时，仅在内容确实变化时才发请求，
 * 避免「点进输入框又点出来」也产生一次 PATCH。
 */
function DialogueRow({
  line,
  generating,
  onGenerate,
  onSaved,
}: {
  line: ShotDialogLineRead
  generating: boolean
  onGenerate: () => void
  onSaved: () => void
}) {
  const [text, setText] = useState(line.text ?? '')
  const [emotion, setEmotion] = useState(line.emotion ?? '')
  const [saving, setSaving] = useState(false)

  const save = async (patch: { text?: string; emotion?: string }) => {
    setSaving(true)
    try {
      await StudioShotDialogLinesService.updateShotDialogLineApiV1StudioShotDialogLinesLineIdPatch({
        lineId: line.id,
        requestBody: patch,
      })
      message.success('已保存')
      onSaved()
    } catch (error) {
      message.error(error instanceof Error ? `保存失败：${error.message}` : '保存失败')
      // 回滚到服务端值，避免界面与数据不一致。
      setText(line.text ?? '')
      setEmotion(line.emotion ?? '')
    } finally {
      setSaving(false)
    }
  }

  const audioUrl = buildFileDownloadUrl(line.generated_audio_file_id)

  return (
    <div className="flex items-start gap-2">
      <div className="w-24 shrink-0 text-xs text-gray-600 mt-1 truncate">
        <Tag color="default" className="!mr-1">
          #{(line.index ?? 0) + 1}
        </Tag>
        {dialogTitle(line)}
      </div>
      <Input.TextArea
        size="small"
        autoSize={{ minRows: 1, maxRows: 3 }}
        value={text}
        disabled={saving}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if ((text ?? '') !== (line.text ?? '')) void save({ text })
        }}
        placeholder="台词内容"
      />
      <Input
        size="small"
        className="w-28 shrink-0"
        value={emotion}
        disabled={saving}
        onChange={(e) => setEmotion(e.target.value)}
        onBlur={() => {
          if ((emotion ?? '') !== (line.emotion ?? '')) void save({ emotion })
        }}
        placeholder="情绪/语气"
      />
      <div className="shrink-0 flex items-center gap-1" style={{ minWidth: 132 }}>
        {audioUrl ? (
          <>
            <audio controls preload="none" style={{ height: 28, width: 96 }} src={audioUrl} />
            <Tooltip title="重新生成配音">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                loading={generating}
                onClick={onGenerate}
              />
            </Tooltip>
          </>
        ) : (
          <Tooltip title="使用说话角色的音色生成配音">
            <Button size="small" icon={<SoundOutlined />} loading={generating} onClick={onGenerate}>
              配音
            </Button>
          </Tooltip>
        )}
      </div>
    </div>
  )
}
