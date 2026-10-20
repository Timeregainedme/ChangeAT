import { describe, expect, it } from 'vitest'
import { cn } from './utils'

/**
 * cn 的行为直接决定组件样式覆盖是否可预期，
 * 这里只锁两条最关键约定：冲突类后者胜出、非冲突类都保留。
 */
describe('cn', () => {
  it('保留非冲突类名', () => {
    expect(cn('px-2', 'text-sm')).toBe('px-2 text-sm')
  })

  it('同族冲突时后者覆盖前者', () => {
    expect(cn('bg-primary', 'bg-destructive')).toBe('bg-destructive')
  })

  it('忽略 falsy 值', () => {
    expect(cn('px-2', false, undefined, null, 'py-1')).toBe('px-2 py-1')
  })
})
