import { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ChevronRight,
  Languages,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  Sun,
  User as UserIcon,
} from 'lucide-react'
import { Button } from '../../components/ui/button'
import { ScrollArea } from '../../components/ui/scroll-area'
import { Separator } from '../../components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '../../components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../../components/ui/dropdown-menu'
import { cn } from '../../lib/utils'
import { useAppStore } from '../../store/useAppStore'
import { useAuthStore } from '../../store/useAuthStore'
import { useThemeStore } from '../../store/useThemeStore'
import { TaskCenter } from '../../pages/aiStudio/components/TaskCenter'
import { TaskRuntimeProvider } from '../../pages/aiStudio/components/TaskRuntimeProvider'
import { getActiveEntryKey, isPathActive, NAV_ENTRIES, type NavLeaf } from './navConfig'
import { resolveBreadcrumbs } from './breadcrumbs'

/** 语言选项，与 i18n 支持的语种保持一致。 */
const LANGUAGES = [
  { value: 'zh-CN', key: 'lang.zh' },
  { value: 'en-US', key: 'lang.en' },
] as const

/**
 * 单个导航项。
 *
 * 收起态只显示图标，因此必须用 Tooltip 补回名称，
 * 否则用户只能靠猜图标含义——这是收起侧边栏最常见的可用性问题。
 */
function NavItem({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavLeaf
  collapsed: boolean
  onNavigate?: () => void
}) {
  const { t } = useTranslation('layout')
  const location = useLocation()
  const active = isPathActive(location.pathname, item.to)
  const Icon = item.icon

  const content = (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      className={cn(
        'group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors',
        collapsed && 'justify-center px-0',
        active
          ? 'bg-primary/10 font-medium text-primary'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
      )}
    >
      <Icon className={cn('h-4 w-4 shrink-0', active && 'text-primary')} />
      {collapsed ? null : <span className="truncate">{t(item.labelKey)}</span>}
    </NavLink>
  )

  if (!collapsed) return content

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent side="right">{t(item.labelKey)}</TooltipContent>
    </Tooltip>
  )
}

/**
 * 应用外壳：侧边导航 + 顶栏 + 内容区。
 *
 * 替换原 antd MainLayout，是「先换壳、再逐页换肉」的第一步：
 * 存量页面不改一行代码就能跑在新壳里，新页面则直接按设计系统写。
 * 保留 TaskRuntimeProvider 与 TaskCenter 的挂载位置，任务轮询行为与原来一致。
 */
export default function AppShell() {
  const { t, i18n } = useTranslation('layout')
  const location = useLocation()
  const navigate = useNavigate()

  const collapsed = useAppStore((s) => s.siderCollapsed)
  const toggleSidebar = useAppStore((s) => s.toggleSider)
  const language = useAppStore((s) => s.language)
  const setLanguage = useAppStore((s) => s.setLanguage)
  const appUser = useAppStore((s) => s.user)
  const authUser = useAuthStore((s) => s.user)
  const clearSession = useAuthStore((s) => s.clearSession)
  const resolvedTheme = useThemeStore((s) => s.resolved)
  const toggleTheme = useThemeStore((s) => s.toggle)

  const activeEntryKey = getActiveEntryKey(location.pathname)
  const [openGroups, setOpenGroups] = useState<string[]>(() => (activeEntryKey ? [activeEntryKey] : []))

  // 进入配置类页面时自动展开对应分组，避免「当前页在收起的分组里」的迷失
  useEffect(() => {
    if (activeEntryKey) {
      setOpenGroups((prev) => (prev.includes(activeEntryKey) ? prev : [...prev, activeEntryKey]))
    }
  }, [activeEntryKey])

  const breadcrumbs = useMemo(() => resolveBreadcrumbs(location.pathname), [location.pathname])

  const displayName = authUser?.display_name || authUser?.username || appUser.name

  /**
   * 切换语言。
   *
   * 同时写 localStorage 与 <html lang>：
   * 前者用于下次启动，后者影响读屏与浏览器断词行为。
   */
  const changeLanguage = (value: string) => {
    setLanguage(value as typeof language)
    void i18n.changeLanguage(value)
    try {
      window.localStorage.setItem('dyeingtime_language', value)
    } catch {
      // 隐私模式下写入失败不影响本次会话
    }
    document.documentElement.lang = value === 'en-US' ? 'en' : 'zh-CN'
  }

  /** 退出登录：先尽力通知后端（无状态 JWT，仅日志用途），再清本地会话。 */
  const logout = () => {
    void fetch('/api/v1/auth/logout', { method: 'POST' }).catch(() => undefined)
    clearSession()
    navigate('/login', { replace: true })
  }

  const toggleGroup = (key: string) => {
    setOpenGroups((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <aside
        className={cn(
          'flex shrink-0 flex-col border-r border-border bg-card transition-[width] duration-200',
          collapsed ? 'w-[68px]' : 'w-[232px]',
        )}
      >
        <div className={cn('flex h-14 items-center gap-2.5 px-4', collapsed && 'justify-center px-0')}>
          <Link to="/projects" className="flex min-w-0 items-center gap-2.5">
            <img src="/logo.png" alt="DyeingTime" className="h-7 w-7 shrink-0" />
            {collapsed ? null : (
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold leading-tight">{t('title')}</div>
                <div className="truncate text-[11px] leading-tight text-muted-foreground">
                  {t('subtitle')}
                </div>
              </div>
            )}
          </Link>
        </div>

        <Separator />

        <ScrollArea className="flex-1">
          <nav className="space-y-0.5 p-2">
            {NAV_ENTRIES.map((entry) => {
              if (!('children' in entry)) {
                return (
                  <NavItem key={entry.key} item={entry} collapsed={collapsed} />
                )
              }

              const GroupIcon = entry.icon
              const open = openGroups.includes(entry.key)
              const groupActive = entry.children.some((child) =>
                isPathActive(location.pathname, child.to),
              )

              return (
                <div key={entry.key} className="pt-1">
                  {collapsed ? (
                    // 收起态不展开分组，仅显示分组图标并提示名称
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div
                          className={cn(
                            'flex h-9 items-center justify-center rounded-md',
                            groupActive ? 'text-primary' : 'text-muted-foreground',
                          )}
                        >
                          <GroupIcon className="h-4 w-4" />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="right">{t(entry.labelKey)}</TooltipContent>
                    </Tooltip>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => toggleGroup(entry.key)}
                        className={cn(
                          'flex h-9 w-full items-center gap-2.5 rounded-md bg-transparent px-2.5 text-sm transition-colors',
                          groupActive
                            ? 'text-primary'
                            : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                        )}
                      >
                        <GroupIcon className="h-4 w-4 shrink-0" />
                        <span className="flex-1 truncate text-left">{t(entry.labelKey)}</span>
                        <ChevronRight
                          className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')}
                        />
                      </button>
                      {open ? (
                        <div className="mt-0.5 space-y-0.5 pl-3">
                          {entry.children.map((child) => (
                            <NavItem key={child.key} item={child} collapsed={false} />
                          ))}
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
              )
            })}
          </nav>
        </ScrollArea>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-4">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleSidebar}
                aria-label={t('shell.toggleSidebar')}
              >
                {collapsed ? (
                  <PanelLeftOpen className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('shell.toggleSidebar')}</TooltipContent>
          </Tooltip>

          <nav aria-label="breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
            {breadcrumbs.map((item, index) => {
              const last = index === breadcrumbs.length - 1
              return (
                <span key={item.key} className="flex min-w-0 items-center gap-1.5">
                  {index > 0 ? <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" /> : null}
                  {item.to && !last ? (
                    <Link
                      to={item.to}
                      className="truncate text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {t(item.labelKey)}
                    </Link>
                  ) : (
                    <span className={cn('truncate', last ? 'font-medium' : 'text-muted-foreground')}>
                      {t(item.labelKey)}
                    </span>
                  )}
                </span>
              )
            })}
          </nav>

          <div className="ml-auto flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={toggleTheme}
                  aria-label={
                    resolvedTheme === 'dark' ? t('shell.switchToLight') : t('shell.switchToDark')
                  }
                >
                  {resolvedTheme === 'dark' ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {resolvedTheme === 'dark' ? t('shell.switchToLight') : t('shell.switchToDark')}
              </TooltipContent>
            </Tooltip>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={t('shell.language')}>
                  <Languages className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{t('shell.language')}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {LANGUAGES.map((item) => (
                  <DropdownMenuItem
                    key={item.value}
                    onClick={() => changeLanguage(item.value)}
                    className={cn(language === item.value && 'text-primary')}
                  >
                    {t(item.key)}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="ml-1 flex items-center gap-2 rounded-md bg-transparent px-1.5 py-1 transition-colors hover:bg-accent"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-xs font-medium text-secondary-foreground">
                    {displayName.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="hidden text-sm md:inline">{displayName}</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuLabel className="flex items-center gap-1.5">
                  <UserIcon className="h-3.5 w-3.5" />
                  {displayName}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate('/settings')}>
                  <Settings2 className="h-4 w-4" />
                  {t('user.profile')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={logout}>
                  <LogOut className="h-4 w-4" />
                  {t('user.logout')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <TaskRuntimeProvider>
          {/*
            存量 antd 页面固定浅色画布。
            这些页面里仍有硬编码的浅色背景，直接跟随深色主题会变成半深半浅；
            新页面在自己的根节点上用 bg-background 覆盖，从而跟随主题。
          */}
          <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
            <Outlet />
          </main>
          <TaskCenter />
        </TaskRuntimeProvider>
      </div>
    </div>
  )
}
