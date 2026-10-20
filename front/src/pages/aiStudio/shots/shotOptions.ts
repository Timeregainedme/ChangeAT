/**
 * 分镜语义字段（景别/角度/运镜）的中文展示选项。
 *
 * 后端存的是枚举 code（ECU/MS/LS...），前端需要在多个页面展示与下拉选择，
 * 因此集中在这里，避免各页面各写一份、改一处漏一处。
 */
import type { CameraAngle, CameraMovement, CameraShotType } from '../../../services/generated'

export const CAMERA_SHOT_OPTIONS: Array<{ value: CameraShotType; label: string }> = [
  { value: 'ECU', label: '大特写' },
  { value: 'CU', label: '特写' },
  { value: 'MCU', label: '中近景' },
  { value: 'MS', label: '中景' },
  { value: 'MLS', label: '中远景' },
  { value: 'LS', label: '远景' },
  { value: 'ELS', label: '大远景' },
]

export const CAMERA_ANGLE_OPTIONS: Array<{ value: CameraAngle; label: string }> = [
  { value: 'EYE_LEVEL', label: '平视' },
  { value: 'HIGH_ANGLE', label: '高角度' },
  { value: 'LOW_ANGLE', label: '低角度' },
  { value: 'BIRD_EYE', label: '鸟瞰' },
  { value: 'DUTCH', label: '荷兰式' },
  { value: 'OVER_SHOULDER', label: '过肩' },
]

export const CAMERA_MOVEMENT_OPTIONS: Array<{ value: CameraMovement; label: string }> = [
  { value: 'STATIC', label: '固定镜头' },
  { value: 'PAN', label: '平移' },
  { value: 'TILT', label: '俯仰' },
  { value: 'DOLLY_IN', label: '推近' },
  { value: 'DOLLY_OUT', label: '拉远' },
  { value: 'TRACK', label: '跟拍' },
  { value: 'CRANE', label: '摇臂' },
  { value: 'HANDHELD', label: '手持' },
  { value: 'STEADICAM', label: '稳定器' },
  { value: 'ZOOM_IN', label: '变焦推近' },
  { value: 'ZOOM_OUT', label: '变焦拉远' },
]

/** 把枚举 code 转成中文；未知 code 原样返回，避免界面出现空白。 */
export function labelOf<T extends string>(
  options: Array<{ value: T; label: string }>,
  value: T | null | undefined,
): string {
  if (!value) return ''
  return options.find((item) => item.value === value)?.label ?? value
}
