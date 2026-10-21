---
title: "前端设计系统"
description: "记录已落地的前端设计系统：token 体系、组件目录、样式隔离策略与验证方式。"
weight: 9
---

> 本文属于“当前架构”文档，描述**已经生效**的前端基础设施。
> 尚在推进中的页面改造与阶段计划见 [前端重写计划](/docs/plans/frontend-rewrite-plan/)。

## 1. 定位

前端正在从 Ant Design 后台风格迁移到自有设计系统。当前状态是**双轨并行**：

- 新页面与新组件使用 `src/components/ui`（shadcn/ui 风格 + Radix + Tailwind）。
- 存量页面继续使用 Ant Design，按业务流程顺序逐页替换，不做一次性重写。

两套体系共存在同一张页面里是允许的，但**不允许新代码再引入 antd**。

## 2. 技术选型（已安装）

| 能力 | 选型 | 用途 |
|---|---|---|
| 设计系统底座 | shadcn/ui 风格组件 + Radix UI | 可访问性由 Radix 保证，样式完全可控 |
| 样式 | Tailwind CSS 3 + CSS variables | 主题切换、低层样式复用 |
| 服务端状态 | TanStack Query 5 | 缓存、失效、乐观更新 |
| 客户端状态 | Zustand | 主题、布局等本地偏好 |
| 动效 | Framer Motion | 页面切换、面板、看板拖拽 |
| 拖拽 | @dnd-kit | 镜头看板列间拖拽（替代已废弃的 react-beautiful-dnd） |
| 表单 | React Hook Form + Zod | 校验与提交状态 |
| 图标 | lucide-react | 新组件图标源 |
| 单测 | Vitest + Testing Library | 组件与纯函数 |
| E2E | Playwright | 关键链路 |

## 3. 目录职责

```text
front/src/
  app/                  页面级装配：Providers、dev-only 预览页
  components/ui/        无业务语义的设计系统组件
  features/             按业务域组织（后续页面迁移落点）
  lib/                  工具函数、QueryClient、query key
  store/                Zustand stores（沿用存量目录名）
  test/                 单测全局 setup
front/e2e/              Playwright 用例
```

约定：

- `components/ui` 内不出现业务字段名，也不 import 业务 store。
- 业务状态色在 `features` 层组装，徽标组件本身不内置状态词典。
- 新页面放 `app/` + `features/`，存量 `pages/aiStudio/*` 保持原状直到被替换。

## 4. Token 体系

颜色全部走 CSS variables（`src/index.css`），通过 `<html class="dark">` 切换深浅主题，不重建 Tailwind 配置。

### 基础语义色

`background / foreground / card / popover / primary / secondary / muted / accent / destructive / border / input / ring`

### 三组状态色（互不替代）

| 组 | token | 对应语义 |
|---|---|---|
| `state-*` | `pending` / `ready` | 镜头信息提取确认状态（`shot.status`） |
| `run-*` | `running` / `success` / `failed` / `idle` | 运行时任务状态 |
| `ready-*` | `blocked` / `partial` / `complete` | 视频生成准备度（`video-readiness`） |

这三组刻意分开：页面上任何徽标只能取其中一组，不允许跨组借用颜色，
否则会重新出现「一个颜色在不同位置表示不同状态」的歧义。

## 5. 样式隔离策略（重要）

Tailwind 的 `preflight` **必须保持关闭**（`tailwind.config.js` 的 `corePlugins`）。

原因是一次真实回归：开启 preflight 后，登录页主按钮变成白底白字。
根因是 preflight 的 `button { background-color: transparent }` 是元素选择器（权重 0,0,1），
而 antd v5 的组件样式全部包在 `:where(...)` 里（权重 0,0,0），
元素选择器直接压过 antd 的按钮底色。

替代方案是两条局部规则（`src/index.css` 的 `@layer base`）：

```css
* , ::before, ::after { border-width: 0; border-style: solid; }
body { @apply bg-background text-foreground antialiased; }
```

只补 shadcn 组件真正依赖的「边框归一化」，其余 preflight 重置（字号、列表、图片 display）不引入。

由此产生的两条编码约定：

1. **组件必须显式声明边框颜色。** 没有 preflight 就不会有默认 `border-color`，
   单独写 `border` 会继承 `currentColor`（深色主题下变成白框）。统一用 `border-border` / `border-input`。
2. **原生表单控件不要直接用。** 没有 preflight 时 `<button>` 保留浏览器 padding 与 `buttonface` 背景，
   `Switch` 的滑块曾因此溢出轨道。新增控件一律用 `components/ui` 里的封装，
   确需原生元素时显式补 `p-0` / `bg-transparent` / `appearance-none`。

## 6. 主题

- 偏好三态：`system` / `light` / `dark`，持久化在 `localStorage` 的 `dyeingtime-theme`。
- `system` 模式监听 `prefers-color-scheme` 变化；用户显式选择后不再跟随系统。
- 切换入口在外壳顶栏，任何页面都可一键切换，不需要回首页。
- 实现见 `src/store/useThemeStore.ts`，启动同步与订阅在 `src/app/providers.tsx`。
- 覆盖范围见第 9 节——主题对**存量 antd 页面同样生效**。

## 7. 全局 Provider

`AppProviders`（`src/app/providers.tsx`）统一挂载：TanStack Query、Tooltip、
主题启动同步。新增全局能力只改这一处，避免出现「某个页面漏包 Provider」。

`src/lib/queryClient.ts` 同时是 query key 的统一出口，避免同一份数据被不同 key 缓存两份。

## 8. 应用外壳

`src/app/shell/AppShell.tsx` 取代了原 antd `MainLayout`，是「先换壳、再逐页换肉」的载体。

导航结构（`navConfig.ts`）：

| 层级 | 入口 | 路由 |
|---|---|---|
| 一级 | 项目 | `/projects` |
| 一级 | 资产 | `/assets` |
| 分组「配置」 | 提示词模板 / 模型管理 / 音色管理 / 设置 | `/prompts` `/models` `/voices` `/settings` |

低频配置收进分组、不进一级导航；任务中心仍是常驻浮窗（`TaskCenter`），
不做成导航项，避免出现「点进去是空页」。

面包屑由 `breadcrumbs.ts` 按路径段查表解析：

- 已收录的路径段显示文案并可点击；
- 未收录的段一律视为实体 ID（项目 / 章节 / 镜头），不显示也不可点。

这条规则取代了旧实现里「按路径位置特判」的拼接逻辑，新增实体路由通常不需要改面包屑。

## 9. 主题覆盖边界

深浅主题**覆盖整个应用**，包括尚未重写的 antd 页面。三件事同时生效才成立：

| 层 | 做法 | 位置 |
|---|---|---|
| 设计系统 | CSS variables + `<html class="dark">` | `src/index.css` |
| antd 组件 | 跟随 `resolvedTheme` 切换 `darkAlgorithm` | `src/main.tsx` |
| 存量字面色值 | 构建期批量生成 `.dark` 覆盖 | `tailwind.config.js` 插件 |
| antd 静态弹层 | `ConfigProvider.config({ theme })` 同步全局主题 | `src/main.tsx` |

细节：

- **存量页面**里有大量按调色板写死的类（`bg-amber-50`、`text-gray-700`）。
  与其逐个文件改，Tailwind 插件在构建期按调色板生成 `.dark` 覆盖：
  浅色底 → 同色系深色 + 透明度，深色字 → 同色系 300 档，浅色边框 → 700 档。
  这样保留了「颜色即语义」（待办仍是琥珀色、失败仍是红色），而不是一律灰掉。
- **antd 静态方法**（`message` / `notification` / `Modal.confirm`）走独立渲染根，
  读的是全局 config 而不是 React context；不同步会在深色下弹出白色提示条。
- 新页面禁止再写字面色值，否则深色下会被这层覆盖规则「意外改色」。

验收方式：深色下逐页看一遍列表、表格、弹窗、提示条，确认没有白底残留与低对比文字。

## 10. 已迁移页面

| 路由 | 新实现 | 旧实现 |
|---|---|---|
| `/projects` | `src/features/projects/ProjectListPage.tsx` | `pages/aiStudio/project/ProjectLobby.tsx`（已删除） |
| `/projects/:id/chapters/:cid/board` | `src/features/shots/ShotBoardPage.tsx` | 新增（原只有表格视图） |
| 全局布局 | `src/app/shell/AppShell.tsx` | `src/layouts/MainLayout.tsx`（已删除） |

项目工作台仪表盘的心智是「一屏只回答三个问题」：现在该做什么、流程走到哪、还剩什么没做。
它删掉了三处重复入口与资产卡片里写死的 80/60/75 假进度条——
装饰性数字会被误读成真实完成度，宁可只展示真实计数。

项目列表页的设计要点：卡片上的「下一步」来自章节准备态，
主按钮文案与点击后跳转的目标严格一致（显示「提取分镜」就跳到分镜页），
不允许出现「文案说下一步、点进去却是首页」。

数据层拆分为 `useProjectList`（列表与增删改）与 `useProjectSummaries`（阶段与镜头流量），
页面只负责展示与路由跳转。摘要接口失败时降级为空摘要，不影响列表浏览。

## 10.1 镜头看板

`/projects/:projectId/chapters/:chapterId/board` 按「待确认 / 生成中 / 已就绪」三列展示镜头。

- 分列优先级写死为「运行时 → 确认状态」：有任务在跑的镜头不会被提示去补确认信息。
- **暂不支持拖拽改状态**：状态推进依赖后端的提取/确认/生成条件校验，
  前端先做只读看板，避免拖出后端不认可的状态。
- 视频生成准备度与资产概览都按需查询：只在打开镜头侧滑时请求 `video-readiness` 与
  `assets-overview`，不在列表层打 N 个请求；侧滑内把「资产 / 信息确认状态 / 运行时任务 / 生成准备度」分块展示。
- 缩略图加载失败时整块收起（`ShotThumb`），不显示破图与 alt 文本。
- 「生成中」列有任务时每 5 秒静默刷新，不切 loading，避免整块看板反复闪骨架。
- 侧滑内可直接编辑**标题、剧本摘录、无需信息提取**三个字段并保存（PATCH 只提交变化字段），
  保存后重新拉取看板，镜头会按新状态自动换列。
- 序号、状态、关联文件不在看板里改：这些字段牵动唯一约束与生成流程，仍走完整编辑页。
- 支持批量操作：列头「全选」→ 批量标记「无需提取」（逐个 PATCH，部分失败时保留失败项可重试）。
  只开放这一种批量动作：它不绕过任何后端校验，而状态推进必须走各自确认流程。
- 入口：章节列表「分镜流转」里的「待确认 N →」直接跳到看板并自动打开批量确认（`?batch=confirm`），
  「更多操作」里也有同样入口；原表格视图保留（`/shots`）。
- 章节横向操作列已收敛为「主动作 + 看板 + 更多」：一键准备、检查流程、配音等低频动作进菜单，
  避免每行 5 个控件把表格挤到横向溢出。

## 11. 设计系统预览页

开发环境访问 `/design`：

- 校验 token、按钮/表单/浮层组件与深浅主题。
- 生产构建下整条路由与动态 import 会被静态裁掉（`import.meta.env.DEV` 三元），不产出 chunk。
- 用途是「组件对照表」，不是给最终用户的功能页。

## 12. 验证方式

```bash
cd front
pnpm exec tsc --noEmit      # 类型
pnpm run lint              # 存量仍有历史告警，新代码必须零错误
pnpm test                  # Vitest
pnpm test:e2e              # Playwright（自带 dev server，端口 7799）
```

E2E 当前覆盖两条链路：

- `/design`：不依赖登录态与后端，验证构建链路、token 与组件渲染；
- `/projects`：用 MSW mock 数据 + 伪造登录态，验证列表渲染、搜索过滤、新建弹窗。

E2E 的 dev server 固定带 `VITE_USE_MOCK=true`，保证用例不依赖后端与真实账号。
