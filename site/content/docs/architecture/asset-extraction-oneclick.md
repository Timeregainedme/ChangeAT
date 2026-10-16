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

前端入口：`ChapterShotsPage` 的「一键创建资产」按钮（`front/src/pages/aiStudio/shots/ChapterShotsPage.tsx::handleBatchCreateAssets`），与「一键提取分镜」并列。

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

## 一键提取资产（全链路）

前端入口：`ChapterShotsPage` 的「一键提取资产」主按钮（`front/src/pages/aiStudio/shots/ChapterShotsPage.tsx::handleOneClickExtractAssets`），排在「一键提取分镜」与「一键创建资产」之前。

它把三个原本分散的步骤串成一条链路，解决「用户不知道该点哪个、也不知道上一步跑完没有」：

```text
（无分镜时）divide-async -> 轮询/通知直到 settle
                     -> extract-async（对全部镜头）-> 直到 settle
                     -> batch-create-assets
```

- **为什么必须在前端串联**：`app/services/worker/task_registry.py` 里没有「切分 + 提取」合并的任务类型，二者是两个独立 task_kind（`script_divide` / `script_extract`），且 `create_divide_task`（`app/services/script_processing_tasks.py:132`）与 `create_extract_task`（同文件 `:282`）都各自落一条 `GenerationTaskLink(relation_entity_id=chapter_id)`。
- **推进方式不是轮询硬等，而是任务 settle 事件**：页面同时持有两个 `useCancelableRelationTask`（`relationType` 分别为 `'chapter_division'` 与 `SCRIPT_EXTRACTION_RELATION_TYPE`），各自的 `onTaskSettled` 经 `advanceOneClickRef` 转发到链路推进函数；`oneClickStageRef` 记录当前阶段（`idle` / `after_divide` / `after_extract`），**只有阶段匹配才继续**，避免干扰用户手动触发的其它任务。
- **镜头范围取全量而非当前页**：`fetchAllShots`（pageSize=500、最多 20 页自动翻页）保证提取覆盖整章；`ChapterShotEditPage` 的「批量提取并刷新」受多选限制，本链路不受此限。
- 单镜头被标记「无需提取」（`skip_extraction`）时会被过滤；全部被过滤则提示「本章节所有分镜都标记为无需提取」并中止（与 `ChapterShotEditPage` 的既有口径一致）。
- 前置校验：无分镜且章节既无精简文本也无原文时直接报错中止，不发起任务。
- 终态：任一阶段任务失败或被取消，链路立即中止并在同一条 message（固定 key `chapter-shots-one-click-extract-assets`，原地替换以避免刷屏）里给出原因；全部成功则提示 `新建/关联/跳过` 计数。
- 两个子任务各自可在页面上取消（「取消提取」/「取消资产提取」按钮），取消同样会让链路中止。

## 一键批量参考图

接口：`POST /api/v1/studio/image-tasks/assets/batch-image-tasks`

- 入参：`{ project_id, asset_type, asset_ids?: [...] }`。
  - `asset_type` 取值即 `BATCH_ASSET_TYPES = ("actor", "character", "scene", "prop", "costume")`（`app/services/studio/batch_asset_images.py`）。**`actor` 与其它四类同等对待**：演员图是角色图的前置参考图，批量出演员图是保证角色一致性的第一步。
  - **`project_id` 必填**：批量任务只处理该项目下的资产。服务先校验项目存在，不存在则 404（`entity_not_found("Project")`）；此前不限定项目会把全库资产都扫进来，是跨项目缺陷。
  - `asset_ids` 可选、**最多 200 条**（`BatchAssetImageTaskRequest.asset_ids` 的 `max_length=200`）；缺省为该类型在**当前项目**下的全部资产。传入但不属于该项目的 ID 不会报错，而是逐条记入 `skipped`（reason = `not in project`）。
  - 服务侧另有 `MAX_BATCH_ASSETS = 200` 上限（`app/services/studio/batch_asset_images.py`）：目标资产数超限**直接报错**，不做截断，避免对全库资产提交无界生成任务（成本保护）。该错误是 `ValueError`，经全局 `ValueError` handler 归一为 `code=400`。
- 服务：`app/services/studio/batch_asset_images.py::create_batch_asset_image_tasks`
  - 每个资产自动选取 front 优先的图片槽位（`pick_primary_image_id`；`is_primary` 仅 CharacterImage 有，其他表按视角+id 排序）。
  - 按 `asset_type` 分派 base draft：`character` → `build_character_image_base_draft`，`actor` → `build_actor_image_base_draft`，其余 → `build_asset_image_base_draft`。
  - 角色没有图片槽位时**按需补一个 front 空槽位**（`_ensure_asset_image_slot`，`is_primary=True`）；**其它类型（含演员）不补槽位**，因为它们创建实体时已按视角预建，缺失即记入 skipped（reason = `no image slot`）。
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

## 页面入口（真实可达）

早先本文把 `ChapterPrep` 记为入口，但该页已**无路由、全仓无 import**（`front/src/App.tsx:31` 把 `/chapters/:chapterId/prep/*` 重定向到 `../shots`），属不可达代码。当前真实入口：

- **一键提取资产（全链路）**：同在 `ChapterShotsPage`，为该页主按钮。没有分镜时先切分镜，再对本章节全部镜头跑资产提取，提取任务结束后自动创建资产；三步由任务 settle 事件串联，中途失败/取消即中止（详见上节）。
- **一键提取分镜**：`ChapterShotsPage`（`/projects/:projectId/chapters/:chapterId/shots`）的「一键提取分镜」按钮，调 `divide-async` 落库分镜；已存在分镜时禁用（需先清空）。
- **一键创建资产**：同在 `ChapterShotsPage`，与「一键提取分镜」并列。调用下节的 `batch-create-assets`（`types` 不传 = 处理全部 pending），完成后提示 `新建/关联/跳过` 计数并刷新分镜列表；无候选时提示先完成信息提取。
- **逐镜候选确认**：`ChapterShotEditPage`（`.../shots/:shotId/edit`），逐候选关联/新建/忽略。
  - 候选不存在时弹「当前无可关联资产，是否新建？」，跳转到资产创建入口并携带上下文：角色 → `/projects/:id?tab=roles&create=1`，场景/道具/服装 → `/assets?tab=<kind>&create=1`。
  - 库里已有同名资产时改为弹「可关联」确认，复用已有实体而非新建。
- **批量生成参考图（一键全部生成）**：`front/src/pages/aiStudio/components/BatchAssetImageButton.tsx`，已接入 4 个项目工作台页签的卡片工具区：
  - 「演员」`tabs/ActorsTab.tsx`（`assetType="actor"`）、「角色」`tabs/RolesTab.tsx`（`assetType="character"`）、「场景」`tabs/ScenesTab.tsx`（`assetType="scene"`）、「道具 / 服装」`tabs/PropsTab.tsx`（`assetType={kind}`，同一组件服务两类）。
  - 按钮不传 `asset_ids`，按当前项目取该类型全部资产；点击先 `Modal.confirm`，再按 `tasks` / `skipped` / `enqueue_failed` 分类汇报结果，并提示「已生成过的资产会再次提交一条新任务（重跑/换角度），不会自动跳过」。
  - 角色按钮额外提示：角色图会引用所绑演员图 + 所绑服装图，演员/服装未出图时角色图会在零参考图情况下生成，建议先跑演员/服装页。
  - 早先本文把入口记为不可达的 `ChapterPrep`；现已改为上述可达页签（`ChapterPrep` 仍为无路由、全仓无 import 的死代码）。

## 提取链路修复记录（2026-10-14）

- 现象：ChapterPrep「一键提取」divide 成功生成分镜，但候选/资产为空。
- 根因：前端按契约传空 `script_division`（注释「服务端从库内分镜重建」），但后端 `generate_extraction_result`
  直接透传空 dict 给 LLM，LLM 无分镜内容可提取，draft 的 shots/characters 全空。
- 修复：`script_processing_worker.py` 新增 `_rebuild_script_division_from_shots(db, chapter_id)`，
  当 `script_division.shots` 为空时从库内 shots（index/title/script_excerpt）重建分镜结构再提取；
  提取结果经 `apply_extraction_result` 正常写入 `shot_extracted_candidates`。
- 验证：测试项目 9cbc4302 重建后提取出 2 角色（林晚/顾言，含音色描述）、1 场景、3 道具；
  一键创建资产接口返回 entity_id 并落库（characters 2 条）。
