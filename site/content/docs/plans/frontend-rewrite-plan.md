---
title: "Frontend Rewrite Plan"
weight: 11
description: "DyeingTime 前端重写计划：流程化、人性化的短剧生产界面。"
---

> 本文属于“任务计划”文档，描述前端重写的目标、UX 方向与实施路径。

## 1. 项目背景

- **项目名称**：DyeingTime（仓库历史名 Jellyfish）
- **定位**：AI 短剧生产工作台，服务 MCN 内部制作团队
- **当前前端**：React 18 / TypeScript / Vite / Ant Design 5 / Zustand / React Router 6 / axios
- **当前痛点**：
  - 操作步骤太碎，跳转多
  - 没有流程引导，新人不知道先做什么
  - 界面拥挤，信息层级弱
  - 任务状态看不懂，缺少业务上下文
- **目标用户**：混合团队（编导、导演、AI 运营），技术素养不同
- **决策方向**：**完全重做视觉**，从 Ant Design 迁移到更现代、更有产品感的组件体系

## 2. 重写目标

1. **流程化**：项目向导 + 镜头看板，让制作流程可视、可推进
2. **人性化**：AI 助手 + 上下文帮助 + 人话文案，降低学习成本
3. **视觉重塑**：脱离 Ant Design 后台感，建立符合短剧制作场景的界面语言
4. **角色感知**：不同角色看到不同操作重点
5. **契约兼容**：继续调用 `/api/v1`，后端 Go 化对前端透明

## 3. 非目标

- 不改动后端 URL 或 OpenAPI 契约
- 不替换 React / Vite / TypeScript
- 第一阶段不做移动端，只做桌面 + 后续平板适配
- 不做全新的 AI 模型，只做人机交互层

## 4. 当前状态速览

| 模块 | 路径 | 状态 |
|---|---|---|
| 入口配置 | `front/vite.config.ts` | 保留 Vite，assets 目录已做特殊处理 |
| 状态管理 | `front/src/`（Zustand） | 保留 Zustand 做客户端状态 |
| 网络请求 | `axios` + generated client | 逐步迁到 TanStack Query |
| UI 组件 | Ant Design 5 | **完全替换** |
| 样式 | Tailwind CSS | 保留并扩展为设计系统 |
| 国际化 | i18next | 保留，文案体系重做 |
| 路由 | React Router 6 | 保留 |

## 5. 设计系统方向

- **组件库**：shadcn/ui（基于 Radix UI + Tailwind CSS，可深度定制）
- **设计 tokens**：颜色、字体、圆角、阴影、间距统一收敛到 CSS variables
- **视觉风格**：
  - 深色/浅色双主题
  - 卡片化、大圆角、柔和阴影
  - 影视感：时间线、缩略图、预览优先
  - 操作密度降低，留白增加
- **动效**：Framer Motion 用于页面切换、看板拖拽、侧滑面板

## 6. 技术栈

```text
React 18
TypeScript 5
Vite 5
Tailwind CSS 3
shadcn/ui + Radix UI
Framer Motion
TanStack Query（React Query）
Zustand
React Hook Form + Zod
React Router 6
i18next
openapi-typescript-codegen  # 继续生成 API client
```

## 7. 目标目录结构

```text
front/src/
  app/                          # 页面级路由组件
    layout.tsx                  # 全局布局
    dashboard/
    project-wizard/
    shot-board/
    shot-detail/
    generation-studio/
    task-center/
    settings/
  features/                     # 按业务域组织
    auth/
    workspace/
    project/
    shot/
    asset/
    generation/
    task/
    file/
  components/ui/                # 设计系统组件
    button.tsx
    card.tsx
    dialog.tsx
    sheet.tsx
    tabs.tsx
    kanban/
    timeline/
    assistant/
  hooks/                        # TanStack Query hooks、通用 hooks
  stores/                       # Zustand stores
  lib/                          # 工具函数、API client 实例
  i18n/                         # 文案与翻译
  types/                        # 业务类型（优先用 generated）
```

## 8. 核心 UX 改造

### 8.1 项目向导（Project Wizard）

新项目不再直接进空白页，而是分步引导：

```text
Step 1: 创建项目      → 剧名、风格、目标平台、画面比例
Step 2: 导入剧本      → 粘贴 / 上传 / 分章节
Step 3: 智能分镜      → 一键拆分，预览镜头列表
Step 4: 确认资产      → 角色/场景/道具候选确认
Step 5: 进入生成      → readiness 检查，提示下一步
```

每步包含：进度条、实时预览、上一步可回退、下一步有条件锁、跳过按钮。

### 8.2 镜头看板（Shot Board）

替代当前表格/列表：

```text
📋 待确认      → 待处理      → 准备中      → 生成中      → 已完成
  镜头 1        镜头 3        镜头 2        镜头 5        镜头 4
  镜头 6        镜头 7        ...
```

- 镜头卡片：缩略图、名称、状态、下一步动作
- 支持拖拽改变状态（后端校验合法性）
- 点击打开**侧滑面板**，不跳转新页
- 顶部按角色切换视图：编导 / 导演 / AI 运营

### 8.3 镜头侧滑面板

```text
镜头 5：雨夜对峙
─────────────────────────
[基本信息] [资产] [对白] [生成]
─────────────────────────
画面描述：雨夜街头，男主...
参考图： [图1] [图2] [+]
生成条件：✅ 有参考图  ❌ 缺时长
[补全生成条件]
```

### 8.4 AI 助手 / Copilot

不是聊天机器人，而是上下文提示：

- 项目首页：“今日待办：3 个镜头待确认、2 个生成任务失败”
- 看板空列：“建议先为镜头 5、7 生成参考图”
- 生成失败：“缺少参考图，[一键补全]”
- 新人首次进入：气泡式引导

### 8.5 上下文帮助

每个复杂功能旁加 `?` 图标，展开：
- 这个功能是做什么的
- 当前步骤在整体流程中的位置
- 一个真实示例
- 常见失败和解决办法

### 8.6 人话文案体系

API 字段名不变，UI 标签全改：

| 技术术语 | 界面文案 |
|---|---|
| shot | 镜头 |
| candidate | 待确认 |
| extraction | 提取 |
| readiness | 生成条件 |
| task | 生成任务 |
| frame image | 关键帧 |
| prompt | 画面描述 / 提示词 |
| adopt | 采纳 |
| revoke | 取消生成 |

## 9. 页面级改造

### Dashboard（项目首页）

- 项目进度条
- 今日待办
- 最近活动流
- 快捷入口：新建项目 / 继续上次 / 查看失败任务

### Shot Board（镜头看板）

- 核心工作区
- 看板视图 / 列表视图切换
- 筛选：按章节 / 按角色 / 按状态
- 批量操作：批量确认 / 批量生成

### Shot Detail（侧滑面板）

- Tab：基本信息 / 资产 / 对白 / 生成历史
- 预览区占 50% 以上空间
- 操作按钮按角色权限显示

### Generation Studio（生成工作室）

- 生成参数卡片化
- 实时预览最终提示词 + 参考图
- 历史版本横向对比
- 生成进度可视化

### Task Center（任务中心）

- 只保留通用、轻量信息
- 显示：什么镜头 / 什么资源 / 状态 / 失败原因 / 修复入口
- 点击跳转对应业务页面，不展示调试上下文

## 10. 与后端配合

- 继续消费 `/api/v1`，使用 `openapi-typescript-codegen` 生成 client
- 新增聚合接口由后端 Go 控制面提供：
  - `GET /api/v1/studio/projects/{id}/board`
  - `GET /api/v1/tasks/{id}/events`（SSE）
- 前端通过 TanStack Query 管理服务端状态、缓存、乐观更新
- 国际化文案由前端主导，后端只返回业务数据

## 11. 90 天实施计划

### Phase 0：设计基线（第 1–2 周）

- 确定设计 tokens（颜色、字体、间距、阴影、圆角）
- 搭建 shadcn/ui 组件库
- 建立新目录结构
- 建立人话文案表（中文/英文）
- 输出信息架构图与关键页面线框

### Phase 1：骨架 + 项目向导（第 3–4 周）

- 新全局布局与导航
- 深色/浅色主题切换
- 项目 Dashboard
- 项目创建向导（5 步）
- 项目列表卡片化

### Phase 2：镜头看板 + 侧滑面板（第 5–8 周）

- 看板视图与镜头卡片
- 侧滑详情面板
- 状态拖拽（需后端支持）
- 角色视图切换
- 筛选与批量操作

### Phase 3：生成工作室 + 任务中心 + AI 助手（第 9–12 周）

- 生成参数卡片化与预览
- 历史版本对比
- 任务中心 human-readable 版本
- AI Copilot 浮窗
- 上下文帮助组件

### Phase 4：打磨（第 13 周起）

- 动效、加载态、空状态
- 平板适配
- 性能优化（虚拟滚动、图片懒加载）
- 可用性测试与文案调优

## 12. 测试策略

- **组件测试**：Vitest + React Testing Library 测 UI 组件
- **页面测试**：Playwright 测关键流程（创建项目 → 分镜 → 生成）
- **契约测试**：生成的 client 类型与后端 OpenAPI 一致
- **视觉回归**：可选 Storybook + Chromatic

## 13. 验收标准

- [ ] 新用户 5 分钟内能走完创建项目到分镜流程
- [ ] 所有技术术语在 UI 上已替换为业务语言
- [ ] 镜头看板可正常拖拽与查看
- [ ] 任务中心能看懂失败原因并一键跳转修复
- [ ] 切换深浅主题无样式错乱
- [ ] 后端 Go 化后前端无需改动即可连上
- [ ] CI 绿（tsc + lint + playwright 核心流程）

## 14. 关键参考文件

- `front/package.json`
- `front/vite.config.ts`
- `front/src/services/generated/`（OpenAPI 生成 client）
- `front/src/` 现有页面结构
- `site/content/docs/architecture/shot-page-boundary.md`
- `site/content/docs/architecture/shot-status-flow.md`
- `site/content/docs/architecture/task-execution.md`
- `AGENTS.md`（前端页面职责约定）
