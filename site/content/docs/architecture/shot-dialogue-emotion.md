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
