import * as React from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>

/**
 * 原生 select 的样式封装。
 *
 * 没有引入 Radix Select：当前用到的场景都是表单里的固定选项（画面风格、画幅），
 * 原生控件在键盘操作、移动端弹层、读屏上的表现已经足够好，
 * 而且用户要在 macOS 上正常使用系统级选择器。复杂筛选器再单独做组合组件。
 */
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ className, children, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(
        'h-9 w-full appearance-none rounded-md border border-input bg-background pl-3 pr-8 text-sm transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
  </div>
))
Select.displayName = 'Select'

export { Select }
