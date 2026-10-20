import { describe, expect, it } from 'vitest'
import { resolveBreadcrumbs } from './breadcrumbs'

/**
 * 面包屑的核心规则是「实体 ID 不显示也不可点」，
 * 这条规则一旦回归，用户会在面包屑里看到一串 UUID 或点到 404。
 */
describe('resolveBreadcrumbs', () => {
  it('静态路径全部可点击', () => {
    const items = resolveBreadcrumbs('/assets')
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ labelKey: 'breadcrumb.assets', to: '/assets' })
  })

  it('实体 ID 段被跳过，且后续层级不再给链接', () => {
    const items = resolveBreadcrumbs('/projects/p1/chapters/c2/studio')

    expect(items.map((item) => item.labelKey)).toEqual([
      'breadcrumb.projects',
      'breadcrumb.chapters',
      'breadcrumb.studio',
    ])
    // 命中动态段后，路径无法安全拼接，一律不给 href
    expect(items[1].to).toBeUndefined()
    expect(items[2].to).toBeUndefined()
  })

  it('末尾的编辑页能正确带上父级', () => {
    const items = resolveBreadcrumbs('/projects/p1/chapters/c2/shots/s3/edit')
    expect(items[items.length - 1]).toMatchObject({ labelKey: 'breadcrumb.edit' })
  })

  it('根路径返回空数组', () => {
    expect(resolveBreadcrumbs('/')).toEqual([])
  })
})
