import { cn } from '../../lib/utils'

/**
 * 骨架屏占位。
 *
 * 用于「已知内容结构、只等数据」的场景，比转圈更能减少布局跳动。
 * 尺寸完全由调用方通过 className 决定，组件本身不假设任何业务形状。
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

export { Skeleton }
