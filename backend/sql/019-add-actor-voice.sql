-- 019: 演员默认音色 + 音色描述（与 characters 同口径）
--
-- 背景（用户需求 m08247）：
--   1) 短剧配音要求「演员和角色都能挂音色，演员第一优先级」：同一演员在不同剧集/不同角色里
--      复用时，音色应能跟着「人」走，而不是每个角色重复配一遍。
--   2) 因此把 characters 上已有的三列（voice_id / voice_source / voice_description）以完全
--      相同的口径复制到 actors 上，形成「演员默认音色 → 角色可覆盖」的两级结构。
--
-- 解析顺序（配合 app/services/studio/audio_task_runner.py 的 _resolve_audio_voice）：
--   显式 voice → characters.voice_id → 该角色的 actors.voice_id → 报错（422）。
--   即：角色音色优先（可覆盖），角色没配时回退到它绑定的演员音色。
--
-- 列口径与 characters 对齐（评审 C-3 / D-9 已确立的结论）：
--   - voice_id / voice_source：NULL 表示未指定；
--   - voice_description：ORM 声明 `Text, nullable=False, default=""`，DDL 侧同步收紧为
--     `TEXT NOT NULL`（与 018 对 characters 的处理一致）。MySQL 对 BLOB/TEXT 一律不允许
--     DEFAULT（5.7/8.0 相同），所以空串默认值只能由 SQLAlchemy 客户端补，DDL 只表达 NOT NULL。
--
-- 幂等：全部通过 information_schema 判定后再执行，可被 compose 重复执行；
--   回填只在「本次刚建出该列」时进行（此时历史行必然为 NULL，是唯一有意义的时机），
--   列已存在时整体跳过，避免每次执行都全表扫 `WHERE voice_description IS NULL`。

-- 1) actors.voice_id
SET @has_actors_voice_id = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'actors'
    AND COLUMN_NAME = 'voice_id'
);

SET @add_actors_voice_id = IF(
  @has_actors_voice_id = 0,
  "ALTER TABLE actors ADD COLUMN voice_id VARCHAR(64) NULL COMMENT '演员默认音色 ID（供应商侧 voice_id；为空表示未指定，角色未配音色时回退到此音色）'",
  'SELECT 1'
);
PREPARE stmt_add_actors_voice_id FROM @add_actors_voice_id;
EXECUTE stmt_add_actors_voice_id;
DEALLOCATE PREPARE stmt_add_actors_voice_id;

-- 2) actors.voice_source
SET @has_actors_voice_source = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'actors'
    AND COLUMN_NAME = 'voice_source'
);

SET @add_actors_voice_source = IF(
  @has_actors_voice_source = 0,
  "ALTER TABLE actors ADD COLUMN voice_source VARCHAR(32) NULL COMMENT '演员默认音色来源（preset 预设音色 / custom 自定义音色；为空时按模型名推断）'",
  'SELECT 1'
);
PREPARE stmt_add_actors_voice_source FROM @add_actors_voice_source;
EXECUTE stmt_add_actors_voice_source;
DEALLOCATE PREPARE stmt_add_actors_voice_source;

-- 3) actors.voice_description（TEXT NOT NULL，向 ORM 对齐；列缺失时才建，建时历史行必然为 NULL，
--    但 TEXT NOT NULL 不允许直接 ADD 带 NULL 数据的列，故先 ADD NULL → 回填 → MODIFY NOT NULL，
--    三步都只在「本次新建」分支里跑。）
SET @has_actors_voice_description = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'actors'
    AND COLUMN_NAME = 'voice_description'
);

SET @add_actors_voice_description = IF(
  @has_actors_voice_description = 0,
  "ALTER TABLE actors ADD COLUMN voice_description TEXT NULL COMMENT '演员音色描述（年龄段/声线/气质/语速等；用于配音选型参考）'",
  'SELECT 1'
);
PREPARE stmt_add_actors_voice_description FROM @add_actors_voice_description;
EXECUTE stmt_add_actors_voice_description;
DEALLOCATE PREPARE stmt_add_actors_voice_description;

SET @backfill_actors_voice_description = IF(
  @has_actors_voice_description = 0,
  "UPDATE actors SET voice_description = '' WHERE voice_description IS NULL",
  'SELECT 1'
);
PREPARE stmt_backfill_actors_voice_description FROM @backfill_actors_voice_description;
EXECUTE stmt_backfill_actors_voice_description;
DEALLOCATE PREPARE stmt_backfill_actors_voice_description;

-- MODIFY 不带 COMMENT 会清空原有注释，因此显式重复列注释。
SET @tighten_actors_voice_description = IF(
  @has_actors_voice_description = 0,
  "ALTER TABLE actors MODIFY COLUMN voice_description TEXT NOT NULL COMMENT '演员音色描述（年龄段/声线/气质/语速等；用于配音选型参考）'",
  'SELECT 1'
);
PREPARE stmt_tighten_actors_voice_description FROM @tighten_actors_voice_description;
EXECUTE stmt_tighten_actors_voice_description;
DEALLOCATE PREPARE stmt_tighten_actors_voice_description;

-- 4) 索引：与 ORM 侧 index=True 对齐（ix_<table>_<column>，SQLAlchemy 默认命名）。
SET @has_ix_actors_voice_id = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'actors'
    AND INDEX_NAME = 'ix_actors_voice_id'
);

SET @add_ix_actors_voice_id = IF(
  @has_ix_actors_voice_id = 0,
  'CREATE INDEX ix_actors_voice_id ON actors (voice_id)',
  'SELECT 1'
);
PREPARE stmt_add_ix_actors_voice_id FROM @add_ix_actors_voice_id;
EXECUTE stmt_add_ix_actors_voice_id;
DEALLOCATE PREPARE stmt_add_ix_actors_voice_id;
