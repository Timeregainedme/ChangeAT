---
title: "项目结构"
weight: 1
description: "快速理解 DyeingTime 的顶层目录和主业务链路。"
---

## 顶层目录

```text
dyeingtime/
├── backend/    # FastAPI、服务层、模型层、AI 工作流
├── front/      # React + Vite 前端工作台
├── deploy/     # Docker 与 Compose 配置
├── docs/       # 仓库内文档与图片素材
└── site/       # Hugo 官网与文档站
```

## 主业务链路

```text
项目 -> 章节 -> 分镜 -> 资产 / 帧图 -> 时间线
```

## 前端职责

- 承接 Studio 工作台页面
- 使用 OpenAPI 生成客户端与后端协作
- 管理项目、章节、分镜、资产、模型与 Agent 相关 UI

## 后端职责

- 提供 `studio / llm / film / script-processing` 等 API
- 管理数据库模型、文件存储与任务状态
- 通过 `chains / services / core.tasks` 接入 AI 能力

## 站点职责

- 官网首页与产品介绍
- 安装、开发、部署与贡献文档
- 后续可以承接版本日志和更新公告

## 推荐阅读路径

1. 先看 [前端说明](/docs/guide/frontend/)
2. 再看 [后端说明](/docs/guide/backend/)
3. 最后看 [AI 工作流](/docs/guide/ai-workflow/)
