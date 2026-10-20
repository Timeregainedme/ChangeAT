---
title: "AI 工作流"
weight: 5
description: "理解 chains、services 和 task 层如何承接 AI 能力。"
---

DyeingTime 的 AI 能力主要由三部分组成：

- 文本处理与实体提取
- 分镜草稿与提示词生成
- 图片 / 视频任务生成与状态追踪

这些能力主要分布在后端的 `app/chains/`、`app/services/` 和 `app/core/tasks/` 中。

## 结构理解方式

### `chains/`

负责 Prompt、Agent 和工作流图定义，偏向“如何思考与编排”。

### `services/`

负责把业务实体、数据库记录和 AI 能力串起来，偏向“如何在系统里使用 AI”。

### `core/tasks/`

负责更接近执行层的图片 / 视频任务逻辑，偏向“如何真正发起任务与追踪状态”。
