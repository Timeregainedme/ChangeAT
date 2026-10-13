-- 010: 角色默认音色 + 生成音频挂载（分镜级 / 台词行级）
--
-- 背景：
--   1) 用户工作流要求「每个角色对应一个音色」，需要把音色持久化在角色上，
--      否则每次 TTS 都要在前端重复选择音色（评审 R-08）。
--   2) 分镜需要能挂载已生成的音频；视频侧已有 shots.generated_video_file_id，
--      音频侧此前只能靠 generation_task_links 反查，分镜读接口拿不到音频（评审新增需求）。
--
-- 粒度说明：
--   - shots.generated_audio_file_id           分镜级音频（整镜配音/旁白）
--   - shot_dialog_lines.generated_audio_file_id 台词行级音频（多角色逐句配音，
--     一个分镜常有多句台词、各自一个音色，只挂分镜级会互相覆盖）
--
-- 幂等：全部通过 information_schema 判定后再 ALTER，可被 compose 重复执行。

-- 1) characters.voice_id
SET @has_characters_voice_id = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'characters'
    AND COLUMN_NAME = 'voice_id'
);

SET @add_characters_voice_id = IF(
  @has_characters_voice_id = 0,
  "ALTER TABLE characters ADD COLUMN voice_id VARCHAR(64) NULL COMMENT '角色默认音色 ID（供应商侧 voice_id；为空表示未指定，TTS 时须显式传音色）'",
  'SELECT 1'
);
PREPARE stmt_add_characters_voice_id FROM @add_characters_voice_id;
EXECUTE stmt_add_characters_voice_id;
DEALLOCATE PREPARE stmt_add_characters_voice_id;

-- 2) characters.voice_source
SET @has_characters_voice_source = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'characters'
    AND COLUMN_NAME = 'voice_source'
);

SET @add_characters_voice_source = IF(
  @has_characters_voice_source = 0,
  "ALTER TABLE characters ADD COLUMN voice_source VARCHAR(32) NULL COMMENT '角色默认音色来源（preset 预设音色 / custom 自定义音色；为空时按模型名推断）'",
  'SELECT 1'
);
PREPARE stmt_add_characters_voice_source FROM @add_characters_voice_source;
EXECUTE stmt_add_characters_voice_source;
DEALLOCATE PREPARE stmt_add_characters_voice_source;

-- 3) shots.generated_audio_file_id（外键指向 files.id，随文件删除置空）
SET @has_shots_generated_audio_file_id = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shots'
    AND COLUMN_NAME = 'generated_audio_file_id'
);

SET @add_shots_generated_audio_file_id = IF(
  @has_shots_generated_audio_file_id = 0,
  "ALTER TABLE shots ADD COLUMN generated_audio_file_id VARCHAR(64) NULL COMMENT '已生成音频关联的文件 ID（FileItem，type=audio）', ADD CONSTRAINT fk_shots_generated_audio_file_id FOREIGN KEY (generated_audio_file_id) REFERENCES files (id) ON DELETE SET NULL",
  'SELECT 1'
);
PREPARE stmt_add_shots_generated_audio_file_id FROM @add_shots_generated_audio_file_id;
EXECUTE stmt_add_shots_generated_audio_file_id;
DEALLOCATE PREPARE stmt_add_shots_generated_audio_file_id;

-- 4) shot_dialog_lines.generated_audio_file_id（外键指向 files.id，随文件删除置空）
SET @has_shot_dialog_lines_generated_audio_file_id = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shot_dialog_lines'
    AND COLUMN_NAME = 'generated_audio_file_id'
);

SET @add_shot_dialog_lines_generated_audio_file_id = IF(
  @has_shot_dialog_lines_generated_audio_file_id = 0,
  "ALTER TABLE shot_dialog_lines ADD COLUMN generated_audio_file_id VARCHAR(64) NULL COMMENT '该台词行已生成音频关联的文件 ID（FileItem，type=audio）', ADD CONSTRAINT fk_shot_dialog_lines_generated_audio_file_id FOREIGN KEY (generated_audio_file_id) REFERENCES files (id) ON DELETE SET NULL",
  'SELECT 1'
);
PREPARE stmt_add_shot_dialog_lines_generated_audio_file_id FROM @add_shot_dialog_lines_generated_audio_file_id;
EXECUTE stmt_add_shot_dialog_lines_generated_audio_file_id;
DEALLOCATE PREPARE stmt_add_shot_dialog_lines_generated_audio_file_id;

-- 5) 索引：与 ORM 侧 index=True 对齐（ix_<table>_<column>，SQLAlchemy 默认命名）。
--    这些列会被「按音色查角色」「按分镜回查音频」命中，缺索引会退化成全表扫。
SET @has_ix_characters_voice_id = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'characters'
    AND INDEX_NAME = 'ix_characters_voice_id'
);

SET @add_ix_characters_voice_id = IF(
  @has_ix_characters_voice_id = 0,
  'CREATE INDEX ix_characters_voice_id ON characters (voice_id)',
  'SELECT 1'
);
PREPARE stmt_add_ix_characters_voice_id FROM @add_ix_characters_voice_id;
EXECUTE stmt_add_ix_characters_voice_id;
DEALLOCATE PREPARE stmt_add_ix_characters_voice_id;

SET @has_ix_shots_generated_audio_file_id = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shots'
    AND INDEX_NAME = 'ix_shots_generated_audio_file_id'
);

SET @add_ix_shots_generated_audio_file_id = IF(
  @has_ix_shots_generated_audio_file_id = 0,
  'CREATE INDEX ix_shots_generated_audio_file_id ON shots (generated_audio_file_id)',
  'SELECT 1'
);
PREPARE stmt_add_ix_shots_generated_audio_file_id FROM @add_ix_shots_generated_audio_file_id;
EXECUTE stmt_add_ix_shots_generated_audio_file_id;
DEALLOCATE PREPARE stmt_add_ix_shots_generated_audio_file_id;

SET @has_ix_shot_dialog_lines_generated_audio_file_id = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shot_dialog_lines'
    AND INDEX_NAME = 'ix_shot_dialog_lines_generated_audio_file_id'
);

SET @add_ix_shot_dialog_lines_generated_audio_file_id = IF(
  @has_ix_shot_dialog_lines_generated_audio_file_id = 0,
  'CREATE INDEX ix_shot_dialog_lines_generated_audio_file_id ON shot_dialog_lines (generated_audio_file_id)',
  'SELECT 1'
);
PREPARE stmt_add_ix_shot_dialog_lines_generated_audio_file_id FROM @add_ix_shot_dialog_lines_generated_audio_file_id;
EXECUTE stmt_add_ix_shot_dialog_lines_generated_audio_file_id;
DEALLOCATE PREPARE stmt_add_ix_shot_dialog_lines_generated_audio_file_id;
