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

-- MySQL 5.7 不允许 TEXT 列带 DEFAULT，应用层（SQLAlchemy）写入时总是显式传值；
-- 这里把历史行回填空串，保证 ORM 读取非空。
UPDATE characters SET voice_description = '' WHERE voice_description IS NULL;
