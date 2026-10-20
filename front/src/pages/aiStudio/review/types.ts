/**
 * 检查流程（P4）页面内部使用的视图类型。
 *
 * 这些类型只服务于「章节检查页」把若干接口的返回聚合成一屏可审的结构，
 * 不与后端 DTO 混用，避免把页面假设固化进 OpenAPI 契约。
 */
import type {
  ShotDetailRead,
  ShotPreparationStateRead,
  ShotRead,
} from '../../../services/generated'

/** 检查页里会出现的资产类型（演员不在镜头资产总览里，故排除）。 */
export type ReviewAssetType = 'character' | 'scene' | 'prop' | 'costume'

/** 已关联资产（按实体去重后的视图）。 */
export type ReviewAssetRow = {
  key: string
  type: ReviewAssetType
  entityId: string
  name: string
  /** 主图/缩略图地址；为空表示尚未出图 */
  thumbnail: string | null
  /** 出现在哪些镜头（如 "#1"、"#3"） */
  shotLabels: string[]
  /** 首次出现的镜头 ID，用于「去镜头」跳转 */
  firstShotId: string
}

/** 尚未确认的提取候选（还停留在 pending）。 */
export type ReviewPendingCandidate = {
  key: string
  type: ReviewAssetType
  name: string
  candidateId: number
  shotId: string
  shotLabel: string
  description: string | null
}

/** 一个镜头的完整检查数据（分镜字段 + 资产总览 + 台词）。 */
export type ShotBundle = {
  shot: ShotRead
  detail: ShotDetailRead | null
  prep: ShotPreparationStateRead | null
}

/** 三段进度统计。 */
export type ReviewProgress = {
  assetsTotal: number
  assetsReady: number
  shotsTotal: number
  shotsReady: number
  linesTotal: number
  linesAudio: number
  pendingCandidates: number
}
