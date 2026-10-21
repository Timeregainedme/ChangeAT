/**
 * 面包屑解析。
 *
 * 之前 MainLayout 里是「按路径段拼字符串 + 按位置特判」，业务一改路由就会错位。
 * 现在改成两层规则：
 *   1. 已知路径段查表拿到文案（layout 命名空间的 breadcrumb.*）；
 *   2. 查不到的段视为实体 ID（项目 ID / 章节 ID / 镜头 ID），既不显示也不可点。
 * 这样新增实体路由时通常不需要改这里，只有新增「可读层级」才需要往表里加一条。
 */
export interface BreadcrumbItem {
  key: string
  labelKey: string
  /** 静态层级才有可跳转路径；实体 ID 层与末级没有。 */
  to?: string
}

/** 已知路径段 → 文案 key。未收录的段会被当作实体 ID 跳过。 */
const SEGMENT_LABEL_KEYS: Record<string, string> = {
  projects: 'breadcrumb.projects',
  assets: 'breadcrumb.assets',
  actors: 'breadcrumb.actors',
  scenes: 'breadcrumb.scenes',
  props: 'breadcrumb.props',
  costumes: 'breadcrumb.costumes',
  prompts: 'breadcrumb.prompts',
  styles: 'breadcrumb.styles',
  models: 'breadcrumb.models',
  voices: 'breadcrumb.voices',
  settings: 'breadcrumb.settings',
  chapters: 'breadcrumb.chapters',
  studio: 'breadcrumb.studio',
  shots: 'breadcrumb.shots',
  review: 'breadcrumb.review',
  editor: 'breadcrumb.editor',
  prep: 'breadcrumb.prep',
  roles: 'breadcrumb.roles',
  edit: 'breadcrumb.edit',
}

/**
 * 把当前路径解析成面包屑。
 *
 * 只有「静态段」会生成可跳转路径；一旦路径里出现实体 ID，
 * 后续层级的 href 都是拼不出来的（缺参数），所以一律不给链接，
 * 避免点一下就跳到 404 或错项目。
 */
export function resolveBreadcrumbs(pathname: string): BreadcrumbItem[] {
  const segments = pathname.split('/').filter(Boolean)
  const items: BreadcrumbItem[] = []
  let href = ''
  let hasDynamicSegment = false

  segments.forEach((segment, index) => {
    const labelKey = SEGMENT_LABEL_KEYS[segment]
    if (!labelKey) {
      // 未收录 → 实体 ID，标记后续层级不可安全拼接
      hasDynamicSegment = true
      return
    }
    href = `${href}/${segment}`
    items.push({
      key: `${index}-${segment}`,
      labelKey,
      to: hasDynamicSegment ? undefined : href,
    })
  })

  return items
}
