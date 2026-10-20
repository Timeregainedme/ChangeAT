import type * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

/**
 * 徽标样式表。
 *
 * 只保留「语义强弱」四种变体，不在这里塞业务状态色：
 * 业务状态（确认状态 / 任务状态 / 生成准备度）由 features 层的状态组件
 * 用 state-* / run-* / ready-* 三组 token 自行组合，避免徽标组件变成状态词典。
 */
const badgeVariants = cva(
  'inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        destructive: 'border-transparent bg-destructive text-destructive-foreground',
        outline: 'text-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

/** 状态与计数用的小标签。 */
function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
