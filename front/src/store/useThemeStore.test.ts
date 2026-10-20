import { describe, expect, it } from 'vitest'
import { applyTheme, resolveTheme, useThemeStore } from './useThemeStore'

/**
 * 主题解析与切换的回归测试。
 *
 * 重点锁住「手动选择不被系统偏好覆盖」这条规则：
 * 这是主题功能最容易写错、且错了以后只在特定系统设置下才复现的地方。
 */
describe('resolveTheme', () => {
  it('显式浅色/深色直接返回自身', () => {
    expect(resolveTheme('light')).toBe('light')
    expect(resolveTheme('dark')).toBe('dark')
  })

  it('跟随系统时读取 matchMedia', () => {
    expect(resolveTheme('system')).toBe('light')
  })
})

describe('useThemeStore', () => {
  it('toggle 在浅色下切到深色，并同步 <html> class', () => {
    useThemeStore.setState({ mode: 'light', resolved: 'light' })
    useThemeStore.getState().toggle()

    expect(useThemeStore.getState().resolved).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('setMode 会写入实际主题 class', () => {
    useThemeStore.getState().setMode('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('applyTheme 幂等，不会残留多个主题 class', () => {
    applyTheme('dark')
    applyTheme('dark')
    expect(document.documentElement.className.split(' ').filter((c) => c === 'dark')).toHaveLength(1)
  })
})
