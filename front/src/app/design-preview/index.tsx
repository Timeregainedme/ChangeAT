import { useState, type ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Separator } from '../../components/ui/separator'
import { Skeleton } from '../../components/ui/skeleton'
import { Switch } from '../../components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '../../components/ui/tooltip'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../../components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '../../components/ui/sheet'
import { useThemeStore } from '../../store/useThemeStore'

/**
 * 设计系统预览页（仅开发环境）。
 *
 * 存在的理由：重写过程中需要一处「组件与 token 的对照表」，
 * 既能肉眼验证深浅主题、状态色和交互组件，也能作为新页面的取色参考。
 * 生产构建里通过 import.meta.env.DEV 静态裁掉，不增加产物体积。
 */

/** 状态色板分段展示：三组语义各自独立，不允许跨组借用。 */
const STATE_TOKENS = [
  { label: '待确认', className: 'bg-state-pending text-state-pending-fg' },
  { label: '已确认', className: 'bg-state-ready text-state-ready-fg' },
]

const RUN_TOKENS = [
  { label: '生成中', className: 'bg-run-running text-run-running-fg' },
  { label: '已完成', className: 'bg-run-success text-run-success-fg' },
  { label: '失败', className: 'bg-run-failed text-run-failed-fg' },
  { label: '未开始', className: 'bg-run-idle text-run-idle-fg' },
]

const READY_TOKENS = [
  { label: '缺条件', className: 'bg-ready-blocked' },
  { label: '部分满足', className: 'bg-ready-partial' },
  { label: '可生成', className: 'bg-ready-complete' },
]

const SURFACES = [
  { label: 'background', className: 'bg-background border border-border' },
  { label: 'card', className: 'bg-card border border-border' },
  { label: 'muted', className: 'bg-muted' },
  { label: 'primary', className: 'bg-primary' },
  { label: 'secondary', className: 'bg-secondary' },
  { label: 'destructive', className: 'bg-destructive' },
]

/** 卡片化的色板区块，避免预览页自己变成一坨散装 div。 */
function TokenSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export default function DesignPreview() {
  const resolved = useThemeStore((s) => s.resolved)
  const toggle = useThemeStore((s) => s.toggle)
  const [switchOn, setSwitchOn] = useState(true)

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">DyeingTime 设计系统</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              仅开发环境可见，用于校验 token、组件与深浅主题。
            </p>
          </div>
          <Button variant="outline" onClick={toggle} aria-label="切换主题">
            {resolved === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            切换主题
          </Button>
        </header>

        <TokenSection title="表面色">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {SURFACES.map((item) => (
              <div key={item.label} className="space-y-2">
                <div className={`h-14 rounded-md ${item.className}`} />
                <p className="text-xs text-muted-foreground">{item.label}</p>
              </div>
            ))}
          </div>
        </TokenSection>

        <div className="grid gap-6 md:grid-cols-3">
          <TokenSection title="信息提取状态">
            <div className="flex flex-wrap gap-2">
              {STATE_TOKENS.map((item) => (
                <span key={item.label} className={`rounded-full px-2.5 py-1 text-xs ${item.className}`}>
                  {item.label}
                </span>
              ))}
            </div>
          </TokenSection>

          <TokenSection title="运行时任务状态">
            <div className="flex flex-wrap gap-2">
              {RUN_TOKENS.map((item) => (
                <span key={item.label} className={`rounded-full px-2.5 py-1 text-xs ${item.className}`}>
                  {item.label}
                </span>
              ))}
            </div>
          </TokenSection>

          <TokenSection title="视频生成准备度">
            <div className="flex flex-wrap gap-2">
              {READY_TOKENS.map((item) => (
                <div key={item.label} className="flex items-center gap-1.5">
                  <span className={`h-2.5 w-2.5 rounded-full ${item.className}`} />
                  <span className="text-xs text-muted-foreground">{item.label}</span>
                </div>
              ))}
            </div>
          </TokenSection>
        </div>

        <TokenSection title="按钮">
          <div className="flex flex-wrap items-center gap-3">
            <Button>生成参考图</Button>
            <Button variant="secondary">批量确认</Button>
            <Button variant="outline">取消</Button>
            <Button variant="ghost">更多</Button>
            <Button variant="destructive">删除镜头</Button>
            <Button variant="link">查看日志</Button>
            <Button size="sm">小按钮</Button>
            <Button size="icon" variant="outline" aria-label="设置">
              <Sun className="h-4 w-4" />
            </Button>
          </div>
        </TokenSection>

        <TokenSection title="表单与反馈">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="preview-name">镜头名称</Label>
              <Input id="preview-name" placeholder="例如：雨夜对峙" />
            </div>
            <div className="flex items-center justify-between rounded-md border border-border px-4 py-2.5">
              <div>
                <p className="text-sm font-medium">使用台词配音作为参考音频</p>
                <p className="text-xs text-muted-foreground">项目级开关，影响后续所有视频生成</p>
              </div>
              <Switch checked={switchOn} onCheckedChange={setSwitchOn} />
            </div>
          </div>

          <Separator className="my-5" />

          <div className="flex flex-wrap items-center gap-3">
            <Badge>默认</Badge>
            <Badge variant="secondary">次要</Badge>
            <Badge variant="outline">描边</Badge>
            <Badge variant="destructive">失败</Badge>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm">
                  悬浮查看
                </Button>
              </TooltipTrigger>
              <TooltipContent>解释图标或字段含义，不超过一句话</TooltipContent>
            </Tooltip>
          </div>

          <div className="mt-5 space-y-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        </TokenSection>

        <TokenSection title="标签页与浮层">
          <Tabs defaultValue="basic">
            <TabsList>
              <TabsTrigger value="basic">基本信息</TabsTrigger>
              <TabsTrigger value="assets">资产</TabsTrigger>
              <TabsTrigger value="dialogue">对白</TabsTrigger>
              <TabsTrigger value="generate">生成</TabsTrigger>
            </TabsList>
            <TabsContent value="basic" className="pt-3 text-sm text-muted-foreground">
              画面描述、时长、画幅等基础字段。
            </TabsContent>
            <TabsContent value="assets" className="pt-3 text-sm text-muted-foreground">
              角色、场景、道具的候选与采纳状态。
            </TabsContent>
            <TabsContent value="dialogue" className="pt-3 text-sm text-muted-foreground">
              台词、情绪与配音绑定。
            </TabsContent>
            <TabsContent value="generate" className="pt-3 text-sm text-muted-foreground">
              生成参数、参考图与历史版本。
            </TabsContent>
          </Tabs>

          <div className="mt-5 flex gap-3">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline">打开弹窗</Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>确认删除镜头？</DialogTitle>
                  <DialogDescription>删除后关联的关键帧与生成记录一并移除，不可恢复。</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button variant="outline">取消</Button>
                  <Button variant="destructive">确认删除</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Sheet>
              <SheetTrigger asChild>
                <Button variant="outline">打开侧滑面板</Button>
              </SheetTrigger>
              <SheetContent>
                <SheetHeader>
                  <SheetTitle>镜头 5：雨夜对峙</SheetTitle>
                  <SheetDescription>不离开看板即可查看与编辑镜头详情。</SheetDescription>
                </SheetHeader>
                <div className="mt-6 space-y-3 text-sm text-muted-foreground">
                  <p>预览区占主要空间，操作按钮按角色权限显示。</p>
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </TokenSection>
      </div>
    </div>
  )
}
