---
title: "对白情绪与配音"
description: "说明对白行的 emotion 字段从脚本提取到 TTS emotion_description 的贯通链路。"
weight: 13
---

> 本文属于“当前架构”文档，描述当前已经生效的对白情绪机制。

## 一条曾经断掉的数据

脚本提取阶段的 LLM 契约**早就产出** `emotion` 与 `delivery`：

```text
app/schemas/skills/common.py
emotion: 情绪/语气（如：愤怒、平静、哽咽）
```

但候选入库时只取了 `index` / `text` / `line_mode` / `speaker_name` / `target_name`，`payload` 恒为空对象——**`emotion` 被静默丢弃**。结果是配音永远用默认语气，而用户也看不到、改不了情绪。

现在这条数据是贯通的。

## 落库

迁移 `backend/sql/013-add-dialog-line-emotion.sql` 给两张表各加一列：

| 表 | 列 | 说明 |
| --- | --- | --- |
| `shot_dialog_lines` | `emotion VARCHAR(64) NULL` | 配音时作为 TTS `emotion_description` 下发 |
| `shot_extracted_dialogue_candidates` | `emotion VARCHAR(64) NULL` | 来自脚本提取的 `DialogLine.emotion`，确认后带入 `shot_dialog_lines` |

迁移采用 `information_schema` + `PREPARE/EXECUTE` 的幂等写法，可重复执行。

对应 ORM 字段在 `backend/app/models/studio_shots.py`（`ShotDialogLine.emotion`、`ShotExtractedDialogueCandidate.emotion`）。

## 对白说话人显示名

对白候选入库时只保存了角色**名字**（`speaker_name` / `target_name`），而角色可能在之后改名。展示口径此前是反的：行内保存的旧名会盖过角色真名。当前统一为：

> **角色真名优先，行内保存的名字兜底。**

### 解析下沉到一处

实现全部收敛在 `backend/app/services/studio/shot_dialogs.py`：

| 函数 | 职责 |
| --- | --- |
| `pick_display_name(name_map, *, character_id, fallback_name)` | 单个显示名：能解析到角色就用角色真名，否则**原样回落**行内名字 |
| `load_character_display_names(db, *, character_ids)` | **一次批量查询**角色名，返回 `角色 ID → 真名`；允许入参含 `None` 与重复值，只保留名字非空的角色 |
| `to_display_reads(db, rows)` | 把 `ShotDialogLine` 行组装为已解析显示名的 `ShotDialogLineRead` 列表 |

- 批量查询是前提：显示名解析**不做 N+1**，一次查询覆盖当前这批行的全部 `speaker_character_id` / `target_character_id`。
- `pick_display_name` 刻意**不做 `fallback_name or ...` 之类的空串归一**：入参是空串就返回空串，是 `None` 就返回 `None`，由各调用方按自己的契约决定空值展示——空串与 `None` 保持各自原样，不会被吞成同一个值。
- 解析只发生在**展示层，不回写数据库**，避免历史行内名字被静默抹掉。

### 复用范围

同一口径已统一供以下展示链路复用（此前只有分页列表做了兜底，主编辑页仍显示「未知」）：

| 链路 | 入口 | 说明 |
| --- | --- | --- |
| 对白分页列表 | `shot_dialogs.py::list_paginated` | 分页后经 `to_display_reads` 解析 |
| 按镜头读取全部对白 | `shot_dialogs.py::list_by_shot` | **返回读模型而非 ORM 行**，供准备页等链路复用同一口径 |
| 分镜准备状态（主编辑页） | `shot_preparation_state.py` | 经 `list_saved_dialog_lines_by_shot` 取已解析的对白行 |
| 成片字幕 | `timeline.py::_dialog_speaker_name` | 复用 `pick_display_name`；沿用时间轴原有契约，空值统一归一为 `None`（`TimelineDialogRead.speaker_name` 可空，字幕按「无说话人」处理） |

### 兜底要真正可用：接受候选时反查角色 ID

兜底（以及「角色真名优先」本身）都依赖台词行上的 `speaker_character_id`。因此接受对白候选时会反查并写入该字段：

- `backend/app/services/studio/shot_extracted_dialogue_candidates.py::mark_accepted` 调用 `_resolve_character_id_by_name`，按 **`project_id + name` 精确匹配**（由 `shot_id → chapter → project_id` 反查项目范围，项目内同名取 ID 最小者，保证结果稳定可复现）解析 `speaker_character_id` 与 `target_character_id`；
- 名字为空、镜头/章节缺失或项目内无同名角色时写入 `None`，此时展示层回落到行内名字——这正是「兜底」存在的意义。

### 前端旁白标签

`front/src/pages/aiStudio/shots/components/ChapterShotDialogueConfirmation.tsx` 的接受/确认弹窗：有说话人时按上面的口径显示真名（或行内名）；**没有说话人时按对白模式回落——`VOICE_OVER`（旁白）显式显示「旁白」，其余才显示「未知」**，不再出现「未知 → 未知」这种把旁白和真正的未知说话人混为一谈的展示。

## 候选阶段

`backend/app/services/studio/shot_extracted_dialogue_candidates.py`：

- 新增 `_clean_emotion(value)`：`strip()`；空值归一为 `None`；**截断到 64 字符**。截断是必要的——`varchar(64)` 在严格模式下超长会让**整条提取结果**报错，不能只丢一个字段。
- `_build_candidates_from_shot_draft` 构造候选时带上 `emotion`。
- `mark_accepted` 落 `ShotDialogLine` 时：

```python
emotion=(_clean_emotion(body.emotion) if body.emotion is not None else _clean_emotion(row.emotion))
```

即**接受时显式传入的情绪优先，为空则沿用候选上的情绪**。

## 接口契约

`backend/app/schemas/studio/shots.py` 中以下模型都带上 `emotion`：

```text
ShotDialogLineBase                 -> 读出
ShotDialogLineCreate               -> 手工新增
ShotDialogLineUpdate               -> 编辑
ShotExtractedDialogueCandidateRead -> 候选展示
ShotExtractedDialogueCandidateAcceptRequest -> 接受时覆盖
```

前端在 `ChapterShotEditPage.tsx` 与 `components/ChapterShotDialogueConfirmation.tsx` 提供情绪编辑入口。

## 下发到 TTS

`backend/app/services/studio/audio_task_runner.py`：

- `_resolve_audio_target` 的返回类型从 5 元组变为 **6 元组**，末位是 `line_emotion`：

```python
line_emotion = (getattr(line, "emotion", "") or "").strip() or None
```

仅在传 `dialog_line_id` 时取值。

- `create_audio_task_and_link` 解包 6 个值，并让**显式参数优先于对白行自带情绪**：

```python
emotion = (emotion or "").strip() or resolved_emotion
```

- 最终写进任务入参 `input_payload["emotion"]`，落在任务 payload 的 `run_args.input.emotion`。

注意音频任务与视频任务的 payload 结构不同：视频是 `run_args.input.{model, ratio, prompt, seconds, reference_images}`，音频是 `run_args.input.{text, model, voice, format, emotion, voice_source}`。

## 测试

`backend/tests/test_shot_dialogue_emotion.py` 覆盖：

- `_clean_emotion` 的空值归一与 64 字符截断；
- 提取候选带 emotion / 空白 emotion 归一为 `None` / 空 `text` 跳过；
- 接受时沿用候选 emotion、显式覆盖、无 emotion 保持 `None`。

`backend/tests/test_audio_task_runner.py` 覆盖 `_resolve_audio_target` 返回 6 元组且带回 `emotion`。
