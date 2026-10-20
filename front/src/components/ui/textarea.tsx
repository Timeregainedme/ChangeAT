import * as React from 'react'
import { cn } from '../../lib/utils'

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>

/**
 * 多行文本框。
 *
 * 最小高度按「三行正文」给，避免弹窗里的描述字段一开始只有一条缝；
 * 允许纵向拉伸但不允许横向拉伸，防止把弹窗撑破。
 */
const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'flex min-h-[80px] w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm',
        'placeholder:text-muted-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export { Textarea }
