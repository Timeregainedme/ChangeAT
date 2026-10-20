import { Button, Input, Spin, Tooltip } from 'antd'
import {
  DeleteOutlined,
  FireOutlined,
  PlusOutlined,
  ReloadOutlined,
  SmileOutlined,
  SoundOutlined,
} from '@ant-design/icons'
import type {
  DialogueLineMode,
  ShotDialogLineRead,
  ShotExtractionSummaryRead,
  ShotExtractedDialogueCandidateRead,
} from '../../../../services/generated'
import { buildFileDownloadUrl } from '../../assets/utils'

/** 对白标题：角色名缺失时按对白模式回落，旁白显式显示「旁白」而不是含混的「未知」。 */
function dialogTitle(
  speaker?: string | null,
  target?: string | null,
  lineMode?: DialogueLineMode | null,
) {
  const s = (speaker ?? '').trim()
  const t = (target ?? '').trim()
  // 旁白（VOICE_OVER）没有具体说话角色：显式回落「旁白」，与真正的「未知说话人」区分开。
  const speakerLabel = s || (lineMode === 'VOICE_OVER' ? '旁白' : '未知')
  return `${speakerLabel} → ${t || '未知'}`
}

type ChapterShotDialogueConfirmationProps = {
  extraction: ShotExtractionSummaryRead
  savedDialogLines: ShotDialogLineRead[]
  /** 正在生成配音的台词行 id 集合 */
  audioGeneratingIds?: Record<number, boolean>
  /** 触发生成配音（按台词行） */
  onGenerateAudio?: (lineId: number) => void
  /** 为当前镜头所有未配音台词生成（镜头级批量） */
  onGenerateAllAudio?: () => void
  /** 镜头级批量配音进行中 */
  batchAudioGenerating?: boolean
  extractedDialogLines: ShotExtractedDialogueCandidateRead[]
  batchDialogAdding: boolean
  dialogLoading: boolean
  dialogDeletingIds: Record<number, boolean>
  dialogAddingKeys: Record<string, boolean>
  onAcceptAll: () => void
  onIgnoreAll: () => void
  onDeleteSavedDialogLine: (lineId: number) => void
  onUpdateSavedDialogText: (lineId: number, text: string) => void
  onUpdateSavedDialogEmotion: (lineId: number, emotion: string) => void
  onAddExtractedDialogLine: (line: ShotExtractedDialogueCandidateRead) => void
  onIgnoreExtractedDialogLine: (line: ShotExtractedDialogueCandidateRead) => void
  onUpdateExtractedDialogText: (candidateId: number, text: string) => void
  onUpdateExtractedDialogEmotion: (candidateId: number, emotion: string) => void
}

export function ChapterShotDialogueConfirmation({
  extraction,
  savedDialogLines,
  audioGeneratingIds = {},
  onGenerateAudio,
  onGenerateAllAudio,
  batchAudioGenerating = false,
  extractedDialogLines,
  batchDialogAdding,
  dialogLoading,
  dialogDeletingIds,
  dialogAddingKeys,
  onAcceptAll,
  onIgnoreAll,
  onDeleteSavedDialogLine,
  onUpdateSavedDialogText,
  onUpdateSavedDialogEmotion,
  onAddExtractedDialogLine,
  onIgnoreExtractedDialogLine,
  onUpdateExtractedDialogText,
  onUpdateExtractedDialogEmotion,
}: ChapterShotDialogueConfirmationProps) {
  const pendingCount = extractedDialogLines.length
  const dialogueStatus = (() => {
    if (extraction.state === 'skipped') {
      return { text: '已跳过', tone: 'blue' as const }
    }
    if (extraction.state === 'not_extracted') {
      return { text: '未提取', tone: 'gold' as const }
    }
    if ((extraction.dialogue_candidate_total ?? 0) === 0 && extraction.state === 'extracted_empty') {
      return { text: '已提取无候选', tone: 'default' as const }
    }
    if (pendingCount > 0) {
      return { text: `待处理 ${pendingCount}`, tone: 'gold' as const }
    }
    return { text: '已完成', tone: 'green' as const }
  })()
  const emptyStateText =
    extraction.state === 'skipped'
      ? '当前镜头已标记为无需提取，对白候选已按完成处理'
      : extraction.state === 'not_extracted'
        ? '当前还没有执行提取，先在上方点击“提取并刷新候选”'
        : extraction.state === 'extracted_empty'
          ? '已执行提取，但当前没有识别到对白候选'
          : '当前没有待确认对白；如果需要，也可以直接补录最终对白'

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white/80 px-4 py-4">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-900 px-1.5 text-[11px] font-semibold text-white">
              2.2
            </span>
            <div className="text-sm font-medium text-slate-900">对白确认</div>
            <span
              className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium"
              style={{
                background:
                  dialogueStatus.tone === 'green'
                    ? '#dcfce7'
                    : dialogueStatus.tone === 'blue'
                      ? '#dbeafe'
                      : dialogueStatus.tone === 'default'
                        ? '#f1f5f9'
                        : '#fef3c7',
                color:
                  dialogueStatus.tone === 'green'
                    ? '#166534'
                    : dialogueStatus.tone === 'blue'
                      ? '#1d4ed8'
                      : dialogueStatus.tone === 'default'
                        ? '#475569'
                        : '#92400e',
              }}
            >
              {dialogueStatus.text}
            </span>
          </div>
          <div className="text-[11px] text-slate-500 mt-1">这里处理系统提取出的对白候选，并确认最终对白内容。</div>
        </div>
        <div className="flex items-center gap-2">
          {savedDialogLines.length > 0 && onGenerateAllAudio ? (
            <Tooltip title="为当前镜头所有未配音的台词依次生成配音（用各自说话角色的音色）">
              <Button
                size="small"
                icon={<SoundOutlined />}
                loading={!!batchAudioGenerating}
                onClick={onGenerateAllAudio}
              >
                本镜头全部配音
              </Button>
            </Tooltip>
          ) : null}
          {extractedDialogLines.length > 0 ? (
            <>
              <Button size="small" loading={batchDialogAdding} onClick={onAcceptAll}>
                全部接受
              </Button>
              <Button size="small" disabled={batchDialogAdding} onClick={onIgnoreAll}>
                全部忽略
              </Button>
            </>
          ) : null}
          {dialogLoading ? <Spin size="small" /> : null}
        </div>
      </div>

      <div className="space-y-2">
        {savedDialogLines.length === 0 && extractedDialogLines.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-5 text-xs text-slate-500">
            {emptyStateText}
          </div>
        ) : null}

        {savedDialogLines.length > 0 ? (
          <div className="space-y-2">
            {savedDialogLines
              .slice()
              .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
              .map((l) => (
                <div key={l.id} className="flex items-start gap-2">
                  <Tooltip title="已保存">
                    <span className="mt-1 text-gray-500">
                      <SmileOutlined />
                    </span>
                  </Tooltip>
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    loading={!!dialogDeletingIds[l.id]}
                    onClick={() => onDeleteSavedDialogLine(l.id)}
                  />
                  <div className="w-36 shrink-0 text-xs text-gray-700 mt-1 truncate">
                    {dialogTitle(l.speaker_name, l.target_name, l.line_mode)}
                  </div>
                  <Input.TextArea
                    value={l.text ?? ''}
                    onChange={(e) => onUpdateSavedDialogText(l.id, e.target.value)}
                    autoSize={{ minRows: 1, maxRows: 4 }}
                    placeholder="对白内容"
                  />
                  <Input
                    className="w-28 shrink-0"
                    size="small"
                    value={l.emotion ?? ''}
                    onChange={(e) => onUpdateSavedDialogEmotion(l.id, e.target.value)}
                    placeholder="情绪/语气"
                  />
                  {/* 配音：有音频则直接可播放，并可重新生成；无音频则提供生成入口。
                      音频会作为参考音频进入视频生成（需同时有参考图）。 */}
                  <div className="shrink-0 flex items-center gap-1" style={{ minWidth: 132 }}>
                    {l.generated_audio_file_id ? (
                      <>
                        <audio
                          controls
                          preload="none"
                          style={{ height: 28, width: 96 }}
                          src={buildFileDownloadUrl(l.generated_audio_file_id) ?? undefined}
                        />
                        <Tooltip title="重新生成配音">
                          <Button
                            type="text"
                            size="small"
                            icon={<ReloadOutlined />}
                            loading={!!audioGeneratingIds[l.id]}
                            onClick={() => onGenerateAudio?.(l.id)}
                          />
                        </Tooltip>
                      </>
                    ) : (
                      <Tooltip title="为该句生成配音（使用说话角色的音色）">
                        <Button
                          size="small"
                          icon={<SoundOutlined />}
                          loading={!!audioGeneratingIds[l.id]}
                          onClick={() => onGenerateAudio?.(l.id)}
                        >
                          配音
                        </Button>
                      </Tooltip>
                    )}
                  </div>
                </div>
              ))}
          </div>
        ) : null}

        {extractedDialogLines.length > 0 ? (
          <div className="space-y-2">
            {extractedDialogLines.map((l) => (
              <div key={l.id} className="flex items-start gap-2">
                <Tooltip title="新提取">
                  <span className="mt-1 text-red-600">
                    <FireOutlined />
                  </span>
                </Tooltip>
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  loading={!!dialogAddingKeys[String(l.id)]}
                  onClick={() => onAddExtractedDialogLine(l)}
                />
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  loading={!!dialogAddingKeys[String(l.id)]}
                  onClick={() => onIgnoreExtractedDialogLine(l)}
                />
                <div className="w-36 shrink-0 text-xs text-gray-700 mt-1 truncate">
                  {dialogTitle(l.speaker_name, l.target_name, l.line_mode)}
                </div>
                <Input.TextArea
                  value={l.text ?? ''}
                  onChange={(e) => onUpdateExtractedDialogText(l.id, e.target.value)}
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  placeholder="对白内容"
                />
                <Input
                  className="w-28 shrink-0"
                  size="small"
                  value={l.emotion ?? ''}
                  onChange={(e) => onUpdateExtractedDialogEmotion(l.id, e.target.value)}
                  placeholder="情绪/语气"
                />
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}
