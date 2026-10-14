---
title: "一键提取资产与批量参考图链路"
description: "面向开发者说明 ToonFlow 式工作流：一键提取分镜与资产、批量创建资产、批量生成参考图并自动回链到关键帧/视频提示词。"
weight: 14
---

> 本文属于“当前架构”文档，描述当前真实生效的实现。

## 背景

短剧生产（40–150 集）要求跨集复用人物形象与场景，保持一致性。为此在“剧本 → 分镜 → 资产 → 参考图 → 关键帧/视频提示词”链路上提供一键化入口：

- 一键提取：剧本输入后同时产出分镜与各类资产候选（人物/场景/道具/服装，含音色描述）。
- 一键创建资产：把提取候选批量落库为真实实体并关联到分镜。
- 一键批量参考图：为资产批量创建图片生成任务（支持抽卡）。
- 参考图回链：资产图生成后，关键帧与视频提示词自动携带参考图（无需手工维护）。

## 提取链路（已有）

```text
divide-async -> 分镜落库(shots)
extract-async -> 候选落库(shot_extracted_candidates，含 payload.description / voice_description)
```

- `ElementExtractorAgent` 输出全局 characters/scenes/props/costumes 与逐镜引用（name-based）。
- 提取候选写入 `shot_extracted_candidates`（status: pending/linked/ignored），并随 `payload` 保留 description 与 voice_description。
- 角色音色：有对白的角色输出 `voice_description`（年龄段/声线/气质/语速），落库到 `characters.voice_description`（迁移 016）。

## 一键创建资产

接口：`POST /api/v1/studio/shots/extracted-candidates/batch-create-assets`

- 入参：`{ chapter_id, types?: [character|scene|prop|costume] }`，缺省处理该章节全部 pending 候选。
- 服务：`app/services/studio/batch_candidate_assets.py::create_assets_from_extraction_candidates`
  - 同名实体查重：character 按 `project_id + name`；scene/prop/costume 通过项目关联表限定项目后按 `name` 查重。
  - 不存在 → 用候选 payload（description/voice_description）创建实体，并绑定候选所在分镜（复用 `create_entity`）。
  - 已存在 → 直接关联已有实体。
  - 无论新建还是关联，候选都标记为 `linked`。
- 返回：`{ created, linked, skipped }`（逐候选明细）。

## 一键批量参考图

接口：`POST /api/v1/studio/image-tasks/assets/batch-image-tasks`

- 入参：`{ asset_type, asset_ids?: [...] }`，缺省为该类型全部资产。
- 服务：`app/services/studio/batch_asset_images.py::create_batch_asset_image_tasks`
  - 每个资产自动选取 front 优先的图片槽位（`pick_primary_image_id`；`is_primary` 仅 CharacterImage 有，其他表按视角+id 排序）。
  - 复用资产图片的 base draft + derive preview 生成提示词，再 `create_image_task_and_link` 建任务。
  - 单个资产失败不阻断批量（记入 skipped）。
- 返回：`{ tasks: [{asset_id, task_id, prompt}], skipped: [...] }`。

## 参考图回链（已有机制，无需额外维护）

- 关键帧：`build_frame_context` / `build_ordered_shot_frame_references` 按 角色→场景→道具→服装 收集 `ShotLinkedAssetItem.file_id` 生成 `图N`。
- 视频提示词：`build_shot_video_prompt_pack` + `_collect_asset_references` 同样按该优先级收集。
- 结论：**只要资产图存在且 file_id 非空，关键帧与视频提示词会自动携带参考图**；前置工作（资产创建 + 批量出图）完成后即自动生效。

## 页面（ChapterPrep）

- “智能提取”：真实调用 divide-async → extract-async → 聚合分镜与候选展示。
- “一键创建资产 / 批量生成参考图”：调用上述两个批量接口；参考图任务提交后提示前往分镜工作室/资产页查看出图与抽卡。
- 实体编辑、从资产库选取等辅助交互仍为 Mock 占位，后续接入实体 CRUD 后可替换。
