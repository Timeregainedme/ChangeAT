---
title: "视频抽卡与版本切换"
description: "说明同一分镜多次生成视频的版本保留、采用切换，以及不采用画布式交互的取舍。"
weight: 12
---

> 本文属于“当前架构”文档，描述当前已经生效的视频版本管理机制。

## 要解决的问题

视频生成是**抽卡**：同一条提示词多跑几次，挑一张最好的。但早期实现里，每次生成都直接覆写 `shots.generated_video_file_id`，上一条结果没有任何入口可以找回来——用户点错一次就永久丢失上一版。

现在改为：**每次生成都留档，当前使用哪一版是一个可切换的指针。**

## 数据模型

版本信息**不新增表**，直接复用既有的任务链路表：

- `generation_task_links`：`resource_type = 'video'`、`relation_type = 'video'`、`relation_entity_id = shot_id`，`file_id` 指向产物文件。
- `generation_tasks`：`task_kind = 'video_generation'`，`payload` 里带本次生成的参数。

对应常量定义在 `backend/app/services/studio/shot_video_versions.py`：

```python
VIDEO_RESOURCE_TYPE = "video"
VIDEO_RELATION_TYPE = "video"
VIDEO_TASK_KIND = "video_generation"
```

“当前版本”不是额外字段，而是**派生**出来的：

```text
is_current = (task_link.file_id == shot.generated_video_file_id)
```

因此不存在两份状态需要同步，也不会出现“指针和版本表不一致”。

## 服务层

```python
async def list_shot_video_versions(db, *, shot_id: str) -> list[ShotVideoVersionRead]
async def adopt_shot_video_version(db, *, shot_id: str, file_id: str) -> Shot
```

`list_shot_video_versions`：

- 用 `select(GenerationTaskLink, GenerationTask).join(...)` 过滤 `resource_type` / `relation_type` / `relation_entity_id` / `task_kind`，避免把别的资源或其他类型的任务混进来。
- 排序 `order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())`——加 `id` 是为了在 `created_at` 相同时仍有稳定顺序。
- 镜头不存在时抛 `ValueError(entity_not_found("Shot"))`，由全局 handler 转 404。
- 从 `payload.run_args.input` 还原 `model` / `ratio` / `prompt` / `seconds`；`prompt` 优先取 `input.prompt`，失败任务回落 `run_args.prompt_preview.prompt`，并带上 `error`。

`adopt_shot_video_version`：

- 只写 `shot.generated_video_file_id = target` 然后 `flush()`。
- **不删除任何历史版本**。
- 会校验 `file_id` 确实属于该镜头，否则 `ValueError("file_id is not a generated video version of this shot")`；空白 `file_id` 抛 `ValueError("file_id is required")`。

## 接口

```text
GET  /api/v1/studio/shots/{shot_id}/video-versions        -> ApiResponse[list[ShotVideoVersionRead]]
POST /api/v1/studio/shots/{shot_id}/video-versions/adopt  -> ApiResponse[ShotRead]
```

`ShotVideoVersionRead`：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 任务 id |
| `file_id` | 产物文件 id，失败时为 `null` |
| `status` | 任务状态 |
| `is_current` | 是否是当前采用的版本 |
| `ratio` / `seconds` | 本次生成参数 |
| `prompt` | 本次使用的提示词 |
| `error` | 失败原因 |
| `created_at` | 生成时间 |

`ShotVideoVersionAdoptRequest` 只有 `file_id` 一个字段。

## 前端交互

视频区在 `front/src/pages/aiStudio/chapter/ChapterStudio.tsx`。

「重新抽卡」按钮不需要用户重填参数：提交成功时会把本次尝试快照存进 `lastVideoSubmit = { prompt, referenceMode, images, ratio }`，按钮用同一份快照重新提交。没有快照时按钮禁用并提示“先生成一次视频后即可重新抽卡”。

「视频版本（抽卡历史）」列表按时间倒序展示每次生成：可播放的版本给视频预览与下载，非当前版本给「采用」按钮，当前版本显示「当前」标签。采用后：

1. 调 adopt 接口切指针；
2. 更新右侧预览；
3. 重新拉取版本列表；
4. 通过 `onRefreshShots` 回调刷新分镜列表，让 `selectedShot.generated_video_file_id` 与后端一致。

最后一步是必要的：如果不回刷，界面上“当前版本”的高亮会停留在旧值。

## 为什么不做画布式

需求明确要求**参考版本保留与替换的能力，但不要画布式交互**。理由是画布（节点图）会引入一套并行的布局、连线与状态模型，而这里的真实诉求只有两点：

- 历史不丢；
- 一键换用。

用“任务链路即版本记录 + 一个可切换指针”就能满足，代价是零新增表、零新增状态同步点。界面形态保持为列表 + 「采用」，与现有的分镜工作台一致。

## 相关文档

- [视频提示词链路与参考图](/docs/architecture/video-prompt-pipeline/)
- [任务执行架构](/docs/architecture/task-execution/)
