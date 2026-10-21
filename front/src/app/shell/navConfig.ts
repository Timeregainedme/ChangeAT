import { Cpu, Files, FolderKanban, Images, Mic, Palette, Settings2, SlidersHorizontal, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * 侧边导航结构。
 *
 * 只放「一级入口 + 配置分组」，不放业务操作：
 *   - 项目、资产是日常主路径，必须一眼可见；
 *   - 提示词 / 模型 / 音色属于低频配置，收进「配置」分组，避免主路径被稀释；
 *   - 任务中心不是页面而是一个常驻浮窗，因此不作为导航项，避免出现「点进去是空页」。
 * labelKey 指向 layout 命名空间的 nav.*，文案改动不需要动这里。
 */
export interface NavLeaf {
  key: string
  labelKey: string
  to: string
  icon: LucideIcon
}

export interface NavGroup {
  key: string
  labelKey: string
  icon: LucideIcon
  children: NavLeaf[]
}

export type NavEntry = NavLeaf | NavGroup

/** 登录后的默认落地页。 */
export const HOME_PATH = '/projects'

export const NAV_ENTRIES: NavEntry[] = [
  { key: 'projects', labelKey: 'nav.projects', to: HOME_PATH, icon: FolderKanban },
  { key: 'assets', labelKey: 'nav.assets', to: '/assets', icon: Images },
  { key: 'files', labelKey: 'nav.files', to: '/files', icon: Files },
  {
    key: 'config',
    labelKey: 'nav.settingsGroup',
    icon: Settings2,
    children: [
      { key: 'prompts', labelKey: 'nav.prompts', to: '/prompts', icon: Sparkles },
      { key: 'styles', labelKey: 'nav.styles', to: '/styles', icon: Palette },
      { key: 'models', labelKey: 'nav.models', to: '/models', icon: Cpu },
      { key: 'voices', labelKey: 'nav.voices', to: '/voices', icon: Mic },
      { key: 'settings', labelKey: 'nav.settings', to: '/settings', icon: SlidersHorizontal },
    ],
  },
]

/**
 * 判断某个入口是否是当前页。
 *
 * 用前缀匹配而不是全等：/projects/:id 这类子路径也应该把一级入口点亮。
 * 结尾补 '/' 再比较，避免 '/assets' 误匹配 '/assets-old' 这种未来可能出现的兄弟路由。
 */
export function isPathActive(pathname: string, to: string): boolean {
  if (pathname === to) return true
  return pathname.startsWith(`${to}/`)
}

/** 找到当前命中的一级入口 key，用于分组默认展开。 */
export function getActiveEntryKey(pathname: string): string | undefined {
  for (const entry of NAV_ENTRIES) {
    if ('children' in entry) {
      if (entry.children.some((child) => isPathActive(pathname, child.to))) return entry.key
    } else if (isPathActive(pathname, entry.to)) {
      return entry.key
    }
  }
  return undefined
}
