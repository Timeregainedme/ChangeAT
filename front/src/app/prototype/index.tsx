import { Link } from 'react-router-dom'
import { ArrowRight, Boxes, FileCode2, LayoutDashboard, Palette, PanelsTopLeft } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'

/**
 * 原型索引页（仅开发环境）。
 *
 * 目的：演示或验收时不用记路由。所有已迁移页面与设计系统入口集中在一页，
 * 每条都标注「是否需要演示数据」以及它属于新设计系统还是存量 antd 页面。
 *
 * 为什么放在 DEV：它是给内部看的导航页，线上用户不需要，构建时整段裁掉。
 */
interface Entry {
  title: string
  description: string
  to: string
  /** 需要 mock 数据里的固定 ID（项目 p1 / 章节 c1 / 镜头 s2）。 */
  needsMockData?: boolean
}

interface Section {
  key: string
  title: string
  description: string
  icon: typeof Palette
  entries: Entry[]
}

const SECTIONS: Section[] = [
  {
    key: 'design',
    title: '设计系统',
    description: 'token、组件与深浅主题的对照表',
    icon: Palette,
    entries: [{ title: '组件与色板', description: '按钮、表单、浮层、状态色', to: '/design' }],
  },
  {
    key: 'migrated',
    title: '已迁移页面（新设计系统）',
    description: '用 components/ui 重写过的页面，支持深浅主题',
    icon: PanelsTopLeft,
    entries: [
      { title: '项目列表', description: '卡片式列表 + 下一步动作', to: '/projects' },
      { title: '文件管理', description: '跨项目素材浏览与下载', to: '/files' },
      {
        title: '镜头看板',
        description: '待确认 / 生成中 / 已就绪三列 + 批量确认',
        to: '/projects/p1/chapters/c1/board',
        needsMockData: true,
      },
      {
        title: '项目设置',
        description: '图片清晰度、视频分辨率、配音开关',
        to: '/projects/p1?tab=settings',
        needsMockData: true,
      },
    ],
  },
  {
    key: 'legacy',
    title: '存量页面（antd）',
    description: '仍在迁移队列中，深色主题通过兼容层生效',
    icon: LayoutDashboard,
    entries: [
      { title: '项目工作台', description: '章节 / 演员 / 角色 / 场景等 tab', to: '/projects/p1', needsMockData: true },
      {
        title: '分镜工作室',
        description: '左列表 + 预览 + 属性面板三栏',
        to: '/projects/p1/chapters/c1/studio',
        needsMockData: true,
      },
      {
        title: '分镜编辑页',
        description: '基础信息与提取确认',
        to: '/projects/p1/chapters/c1/shots/s2/edit',
        needsMockData: true,
      },
      { title: '资产管理', description: '演员 / 场景 / 道具 / 服装', to: '/assets' },
      { title: '模型管理', description: '供应商、模型与默认设置', to: '/models' },
      { title: '提示词模板', description: '模板管理与发布', to: '/prompts' },
      { title: '音色管理', description: '预置与自定义音色', to: '/voices' },
    ],
  },
]

/** 原型索引页本体。 */
export default function PrototypeIndex() {
  const isMock = import.meta.env.VITE_USE_MOCK === 'true'

  return (
    <div className="min-h-screen bg-background px-8 py-8 text-foreground">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <Boxes className="h-5 w-5" />
              原型索引
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              仅开发环境可见。{isMock ? '当前为演示数据模式，下面的示例链接可直接打开。' : '当前未启用演示数据，带「需要演示数据」的链接会请求真实后端。'}
            </p>
          </div>
          <Badge variant={isMock ? 'default' : 'secondary'}>
            {isMock ? '演示数据模式' : '真实后端模式'}
          </Badge>
        </header>

        {SECTIONS.map((section) => {
          const Icon = section.icon
          return (
            <section key={section.key} className="space-y-3">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-base font-semibold">{section.title}</h2>
                <span className="text-xs text-muted-foreground">{section.description}</span>
              </div>

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {section.entries.map((entry) => (
                  <Card key={entry.title} className="flex flex-col">
                    <CardHeader className="pb-2">
                      <CardTitle className="flex items-center justify-between gap-2 text-sm">
                        <span className="truncate">{entry.title}</span>
                        {entry.needsMockData ? (
                          <Badge variant="outline" className="shrink-0 text-[10px]">
                            需要演示数据
                          </Badge>
                        ) : null}
                      </CardTitle>
                      <CardDescription className="line-clamp-2 text-xs">
                        {entry.description}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="mt-auto pt-0">
                      <Button asChild size="sm" variant="ghost" className="px-0 text-primary">
                        <Link to={entry.to}>
                          打开
                          <ArrowRight className="ml-1 h-3.5 w-3.5" />
                        </Link>
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )
        })}

        <footer className="flex items-center gap-2 border-t border-border pt-4 text-xs text-muted-foreground">
          <FileCode2 className="h-3.5 w-3.5" />
          启动方式：<code className="rounded bg-muted px-1.5 py-0.5">pnpm dev:mock</code>
          或 <code className="rounded bg-muted px-1.5 py-0.5">pnpm dev:design</code>
        </footer>
      </div>
    </div>
  )
}
