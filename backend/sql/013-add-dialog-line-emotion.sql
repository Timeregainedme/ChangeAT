-- 013: 台词行情绪（emotion）持久化 —— 打通「脚本提取 → 台词行 → TTS」
--
-- 背景（提示词改造第 2 档 F 项）：
--   脚本处理链路的 LLM 契约 `app/schemas/skills/common.py` 的 DialogLine 早就产出
--   `emotion`（情绪/语气，如「愤怒、平静、哽咽」），优云智算 IndexTTS-2.5 也支持
--   `emotion_description`（supports_emotion=True，上限 200 字符）；但两张表都没有这一列，
--   提取时被静默丢弃，配音时只能手输情绪 —— 属于真实的数据丢失缺陷。
--
-- 落点：
--   - shot_extracted_dialogue_candidates.emotion  提取候选（先落候选，人工确认后转正式台词行）
--   - shot_dialog_lines.emotion                   正式台词行（TTS 直接读这一列）
--
-- 幂等：全部通过 information_schema 判定后再 ALTER，可被 compose 重复执行。

-- 1) shot_dialog_lines.emotion
SET @has_shot_dialog_lines_emotion = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shot_dialog_lines'
    AND COLUMN_NAME = 'emotion'
);

SET @add_shot_dialog_lines_emotion = IF(
  @has_shot_dialog_lines_emotion = 0,
  "ALTER TABLE shot_dialog_lines ADD COLUMN emotion VARCHAR(64) NULL COMMENT '情绪/语气（如：愤怒、平静、哽咽），配音时作为 TTS emotion_description 下发'",
  'SELECT 1'
);
PREPARE stmt_add_shot_dialog_lines_emotion FROM @add_shot_dialog_lines_emotion;
EXECUTE stmt_add_shot_dialog_lines_emotion;
DEALLOCATE PREPARE stmt_add_shot_dialog_lines_emotion;

-- 2) shot_extracted_dialogue_candidates.emotion
SET @has_shot_extracted_dialogue_candidates_emotion = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shot_extracted_dialogue_candidates'
    AND COLUMN_NAME = 'emotion'
);

SET @add_shot_extracted_dialogue_candidates_emotion = IF(
  @has_shot_extracted_dialogue_candidates_emotion = 0,
  "ALTER TABLE shot_extracted_dialogue_candidates ADD COLUMN emotion VARCHAR(64) NULL COMMENT '情绪/语气（来自脚本提取的 DialogLine.emotion），确认后带入 shot_dialog_lines'",
  'SELECT 1'
);
PREPARE stmt_add_shot_extracted_dialogue_candidates_emotion FROM @add_shot_extracted_dialogue_candidates_emotion;
EXECUTE stmt_add_shot_extracted_dialogue_candidates_emotion;
DEALLOCATE PREPARE stmt_add_shot_extracted_dialogue_candidates_emotion;
