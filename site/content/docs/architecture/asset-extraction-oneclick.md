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
- 迁移 018（`backend/sql/018-unify-character-voice-description-not-null.sql`）把该列从 `TEXT NULL` 收紧为 `TEXT NOT NULL`，使 DDL 与 ORM（`Character.voice_description`，`nullable=False`）口径一致：收紧前先回填历史 NULL 为空串，列已是 NOT NULL 时整体跳过（幂等，可重复执行）。

## 一键创建资产

接口：`POST /api/v1/studio/shots/extracted-candidates/batch-create-assets`

- 入参：`{ chapter_id, types?: [character|scene|prop|costume] }`，缺省处理该章节全部 pending 候选。
- `types` 的两种「空」语义不同（`app/services/studio/batch_candidate_assets.py::create_assets_from_extraction_candidates`）：
  - **不传 `types`（`None`）= 不限定类型，处理全部**；
  - **显式传空数组 `[]` = 一个类型都不处理**，直接返回三个空列表；
  - 传入 `character/scene/prop/costume` 之外的取值直接报错。
- 服务：`app/services/studio/batch_candidate_assets.py::create_assets_from_extraction_candidates`
  - 同名实体查重：character 按 `project_id + name`；scene/prop/costume 通过项目关联表限定项目后按 `name` 查重。
  - 不存在 → 用候选 payload（description/voice_description）创建实体，并绑定候选所在分镜（复用 `create_entity`）。
  - 已存在 → 直接关联已有实体。
  - 无论新建还是关联，候选都标记为 `linked`。
- 返回：`{ created, linked, skipped }`（逐候选明细）。

## 一键批量参考图

接口：`POST /api/v1/studio/image-tasks/assets/batch-image-tasks`

- 入参：`{ project_id, asset_type, asset_ids?: [...] }`。
  - **`project_id` 必填**：批量任务只处理该项目下的资产。服务先校验项目存在，不存在则 404（`entity_not_found("Project")`）；此前不限定项目会把全库资产都扫进来，是跨项目缺陷。
  - `asset_ids` 可选、**最多 200 条**（`BatchAssetImageTaskRequest.asset_ids` 的 `max_length=200`）；缺省为该类型在**当前项目**下的全部资产。传入但不属于该项目的 ID 不会报错，而是逐条记入 `skipped`（reason = `not in project`）。
  - 服务侧另有 `MAX_BATCH_ASSETS = 200` 上限（`app/services/studio/batch_asset_images.py`）：目标资产数超限**直接报错**，不做截断，避免对全库资产提交无界生成任务（成本保护）。该错误是 `ValueError`，经全局 `ValueError` handler 归一为 `code=400`。
- 服务：`app/services/studio/batch_asset_images.py::create_batch_asset_image_tasks`
  - 每个资产自动选取 front 优先的图片槽位（`pick_primary_image_id`；`is_primary` 仅 CharacterImage 有，其他表按视角+id 排序）。
  - 角色没有图片槽位时**按需补一个 front 空槽位**（`_ensure_asset_image_slot`，`is_primary=True`）；其他类型补不了，才记入 skipped（reason = `no image slot`）。
  - 复用资产图片的 base draft + derive preview 生成提示词，再 stage 图片生成任务与关联关系（`stage_image_task_and_link`，不提交、不入队）。
  - **单个资产的 stage 包在 SAVEPOINT（`db.begin_nested()`）里**：单个失败只回滚自己并记入 `skipped`（reason = 异常文本），不污染会话、不阻断批量。
  - **两阶段提交**：先把全部资产的 stage 结果收集完，再 `db.commit()` **一次性提交**；提交成功后才逐个入队（`enqueue_task_execution`），避免中途失败留下「部分任务已入队」的半成品。
  - 入队失败的任务会被显式标记为 **failed** 并写入错误原因（`enqueue failed: ...`），不会永久停在 pending，同时记入返回值的 `enqueue_failed`；其余任务继续入队。
- 返回：`{ tasks, skipped, enqueue_failed }`。
  - `tasks`：`[{asset_id, task_id, prompt}]`，**只含已成功入队的任务**。
  - `skipped`：`[{asset_id, reason}]`，含 `not in project` / `no image slot` / stage 异常三类。
  - `enqueue_failed`：`[{asset_id, task_id, reason}]`，已落库但未能入队（对应任务行已被标记 failed）。

## 参考图回链（已有机制，无需额外维护）

- 关键帧：`build_frame_context` / `build_ordered_shot_frame_references` 按 角色→场景→道具→服装 收集 `ShotLinkedAssetItem.file_id` 生成 `图N`。
- 视频提示词：`build_shot_video_prompt_pack` + `_collect_asset_references` 同样按该优先级收集。
- 结论：**只要资产图存在且 file_id 非空，关键帧与视频提示词会自动携带参考图**；前置工作（资产创建 + 批量出图）完成后即自动生效。

## 页面（ChapterPrep）

- “智能提取”：真实调用 divide-async → extract-async → 聚合分镜与候选展示。
- “一键创建资产 / 批量生成参考图”：调用上述两个批量接口；参考图任务提交后提示前往分镜工作室/资产页查看出图与抽卡。
- 实体编辑、从资产库选取等辅助交互仍为 Mock 占位，后续接入实体 CRUD 后可替换。

## 提取链路修复记录（2026-10-14）

- 现象：ChapterPrep「一键提取」divide 成功生成分镜，但候选/资产为空。
- 根因：前端按契约传空 `script_division`（注释「服务端从库内分镜重建」），但后端 `generate_extraction_result`
  直接透传空 dict 给 LLM，LLM 无分镜内容可提取，draft 的 shots/characters 全空。
- 修复：`script_processing_worker.py` 新增 `_rebuild_script_division_from_shots(db, chapter_id)`，
  当 `script_division.shots` 为空时从库内 shots（index/title/script_excerpt）重建分镜结构再提取；
  提取结果经 `apply_extraction_result` 正常写入 `shot_extracted_candidates`。
- 验证：测试项目 9cbc4302 重建后提取出 2 角色（林晚/顾言，含音色描述）、1 场景、3 道具；
  一键创建资产接口返回 entity_id 并落库（characters 2 条）。
