/**
 * 台词配音（TTS）任务助手。
 *
 * 为什么单独抽出：
 *   分镜编辑页与章节检查页都需要「为某句台词生成配音并等到完成」，
 *   而这段流程包含「创建任务 → 轮询状态 → 识别失败原因」，
 *   各处重复实现容易在轮询间隔、超时、错误文案上出现分歧。
 *
 * 约定：
 *   - 只传 `dialog_line_id`，由服务端补全台词文本、说话角色、音色，
 *     并把产物直接写回 `shot_dialog_lines.generated_audio_file_id`；
 *   - 轮询直到 succeeded，失败/取消/超时都抛出带可读信息的 Error，
 *     调用方只需决定「怎么提示用户」。
 */
import { FilmService, StudioAudioTasksService } from '../../../services/generated'

/** 轮询间隔：TTS 通常 10-20 秒完成，2 秒一次足够灵敏且不会打爆接口。 */
const POLL_INTERVAL_MS = 2000
/** 单条配音的等待上限：超过基本可判定为异常，交由用户重试。 */
const DEFAULT_TIMEOUT_MS = 3 * 60 * 1000

export type RunSpeechTaskOptions = {
  timeoutMs?: number
}

/**
 * 为一句台词生成配音，并等待任务进入终态。
 *
 * @param lineId `shot_dialog_lines.id`
 * @throws 任务创建失败、任务失败/取消、或超时
 */
export async function runSpeechTaskForLine(
  lineId: number,
  options?: RunSpeechTaskOptions,
): Promise<void> {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS

  const created = await StudioAudioTasksService.createSpeechTaskApiV1StudioAudioTasksSpeechPost({
    requestBody: { dialog_line_id: lineId },
  })
  const taskId = (created.data as { task_id?: string } | undefined)?.task_id ?? ''
  if (!taskId) throw new Error('未返回任务 ID')

  const startedAt = Date.now()
  let status = ''
  while (Date.now() - startedAt < timeoutMs) {
    const resp = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
    const data = resp.data as { status?: string; error?: string } | undefined
    status = String(data?.status ?? '')
    if (status === 'succeeded') return
    if (status === 'failed' || status === 'cancelled') {
      throw new Error(data?.error || `配音任务${status}`)
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
  }
  throw new Error('配音超时（3 分钟）')
}

/**
 * 把配音失败信息转成用户能采取行动的中文提示。
 *
 * 最常见的失败原因是「说话角色没有配置音色」（后端返回 422），
 * 这里显式点出来，避免用户以为是系统故障。
 */
export function describeSpeechError(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error)
  if (/音色|voice/i.test(detail)) {
    return `配音失败：${detail}（请先在角色或演员上配置音色）`
  }
  return `配音失败：${detail}`
}
