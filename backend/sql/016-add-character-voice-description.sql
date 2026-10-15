-- 016: 角色音色描述（剧本提取产出，供配音选型参考）
--
-- 背景：
--   1) 短剧生产要求「角色音色可复用、跨集一致」；音色 ID（voice_id）由用户后期绑定，
--      但剧本提取阶段应产出角色声音特征描述（年龄段/声线/气质/语速等），作为配音选型依据。
--   2) 描述随 ElementExtractorAgent 的 characters 草稿一并产出，落库后可在资产页/分镜编辑页查看与修改。
--
-- 幂等：通过 information_schema 判定后再 ALTER，可被 compose 重复执行。

SET @has_characters_voice_description = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'characters'
    AND COLUMN_NAME = 'voice_description'
);

SET @add_characters_voice_description = IF(
  @has_characters_voice_description = 0,
  "ALTER TABLE characters ADD COLUMN voice_description TEXT NULL COMMENT '角色音色描述（剧本提取产出：年龄段/声线/气质/语速等；用于配音选型参考）'",
  'SELECT 1'
);
PREPARE stmt_add_characters_voice_description FROM @add_characters_voice_description;
EXECUTE stmt_add_characters_voice_description;
DEALLOCATE PREPARE stmt_add_characters_voice_description;

-- 说明（评审 D-9 修正措辞）：MySQL 对 BLOB/TEXT 类型**一律**不允许 DEFAULT（5.7 与 8.0 相同），
-- 不是 5.7 独有限制。因此「非空且默认空串」这一口径只能由应用层（SQLAlchemy 的客户端默认值
-- default=""）提供，DDL 层只负责 NULL/NOT NULL；列口径的最终统一见
-- 018-unify-character-voice-description-not-null.sql。
--
-- 幂等/降扫描（评审 D-9）：回填只在「本次刚建出该列」时执行 —— 此时历史行必然为 NULL，
-- 是该 UPDATE 唯一有意义的时机。列已存在时整体跳过，避免每次执行都对全表做
-- `WHERE voice_description IS NULL` 扫描；二次执行不报错、不改语义。
SET @backfill_characters_voice_description = IF(
  @has_characters_voice_description = 0,
  "UPDATE characters SET voice_description = '' WHERE voice_description IS NULL",
  'SELECT 1'
);
PREPARE stmt_backfill_characters_voice_description FROM @backfill_characters_voice_description;
EXECUTE stmt_backfill_characters_voice_description;
DEALLOCATE PREPARE stmt_backfill_characters_voice_description;
