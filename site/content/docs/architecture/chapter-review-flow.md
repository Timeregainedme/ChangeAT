---
title: "章节检查流程（参考图 → 分镜 → 对话）"
description: "面向开发者说明章节级检查页的定位、三段结构、可修改范围与数据来源。"
weight: 9
---

> 本文属于“当前架构”文档，描述当前真实生效的实现。

## 为什么需要这一页

分镜编辑页负责“提取与确认”，分镜工作室负责“生成”。两者之间缺少一个**开工前的自检位**：
用户在进入工作室（会产生付费生成）之前，需要把本章用到的素材按固定顺序过一遍。

`ChapterReviewPage` 就是这一页，路由为：

```text
/projects/:projectId/chapters/:chapterId/review
```

## 三段结构

页面固定按以下顺序组织，并可用「上一段 / 下一段」顺序推进：

| 段 | 目标 | 可修改内容 |
| --- | --- | --- |
| ① 参考图 | 本章镜头引用到的角色/服装/场景/道具是否都有参考图 | 缺图补图、已有图重抽；跳转资产/角色维护 |
| ② 分镜 | 逐镜头的生成参数是否完整 | 时长、景别、角度、运镜、场景 |
| ③ 对话 | 台词文案与配音是否就绪 | 台词文本、情绪、单句配音/重抽、镜头级补配音 |

页面顶部展示三段进度（有图数 / 字段完整数 / 已配音数）与待确认候选数。

## 职责边界

检查页**不承担**以下职责，避免退化成第二个编辑器：

- 不提供提取候选的确认入口（候选仍在分镜编辑页处理，页面只给跳转提示）；
- 不提供视频参数配置与成片生成（属于分镜工作室）；
- 不提供资产名称/描述/标签编辑（属于资产页与角色页）。

这条边界的意义：`shot.status` 仍只表示“信息提取确认状态”，
检查页看到 `pending` 时应当引导用户回分镜编辑页，而不是就地替用户确认。

## 数据来源

| 区块 | 接口 |
| --- | --- |
| 章节信息 | `GET /studio/chapters/{chapter_id}` |
| 镜头列表 | `GET /studio/shots?chapter_id=...`（`page_size` 上限 100） |
| 镜头准备状态（资产总览 + 台词 + 待确认数） | `GET /studio/shots/{shot_id}/preparation-state` |
| 分镜字段 | `GET /studio/shot-details/{shot_id}` |
| 保存分镜字段 | `PATCH /studio/shot-details/{shot_id}` |
| 保存台词 | `PATCH /studio/shot-dialog-lines/{line_id}` |
| 补图 / 重抽 | `POST /studio/image-tasks/assets/batch-image-tasks` |
| 配音 | `POST /studio/audio-tasks/speech` + 任务轮询 |

聚合规则：

- 资产按 `type + linked_entity_id` 去重，同一资产出现在多个镜头时合并展示；
- 仅 `candidate_status = pending` 的候选进入“待确认候选”列表；
- 镜头详情可能尚不存在（刚提取未保存），页面用 `allSettled` 容错并在该镜头提示。

## 与实体合并的关系

检查页第一段会暴露“同一资产被提取成两个名字”的问题（例如两个镜头分别引用
「护工工作服」与「护工护理工作服」）。处理入口是资产页 / 角色页的「合并」按钮，
调用 `POST /studio/entities/{entity_type}/merge`；合并规则见
`services/studio/entity_merge.py`。
