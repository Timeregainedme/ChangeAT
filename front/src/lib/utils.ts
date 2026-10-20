import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 合并 className：先拼接，再用 tailwind-merge 消解冲突的原子类。
 *
 * 为什么需要它：组件既接受外部 className 覆盖，又有自身默认样式，
 * 直接字符串拼接会留下「两个 bg-* 同时生效、谁赢看顺序」的隐患。
 * tailwind-merge 保证后传入的类稳定胜出，样式覆盖才是可预期的。
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
