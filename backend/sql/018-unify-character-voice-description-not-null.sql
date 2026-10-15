-- 018: 统一 characters.voice_description 的可空口径（DDL 向 ORM 对齐为 NOT NULL）
--
-- 背景（评审 C-3）：
--   ORM（app/models/studio_assets.py 的 Character.voice_description）声明为
--   `Text, nullable=False, default=""`，而 016 建的是 `TEXT NULL` 再靠 UPDATE 回填空串，
--   两处口径不一致。后果：任何绕过 ORM 的写入（原生 SQL、运维工具、历史脚本）都能落 NULL，
--   ORM 读回来是 `None`，与「该字段读取恒为非空字符串」的契约不符。
--
-- 方案（两种统一方式里选改动面更小的一方）：把 **DDL 向 ORM 对齐**，收紧为 `TEXT NOT NULL`。
--   1) ORM 本来就是 NOT NULL，收紧 DDL 后两边一致，无需改动任何读/写路径；
--   2) 测试库由 `Base.metadata.create_all` 生成，现有测试实际跑的就是 TEXT NOT NULL，
--      说明 ORM 写入路径本来就恒带值，收紧不会破坏既有写入（仓库内也没有任何原生
--      `INSERT INTO characters` 路径）；
--   3) 反过来把 ORM 放宽为 nullable=True，需要连带放宽 `CharacterRead.voice_description: str`
--      等**读取侧**契约（否则 `None` 会直接触发响应校验 500），改动面更大，也会削弱
--      「音色描述可查看」的可读性。
--
-- 关于 DEFAULT：MySQL 对 BLOB/TEXT 类型**一律**不允许 DEFAULT（5.7 与 8.0 相同，评审 D-9），
--   所以 ORM 的 `default=""` 只能是**客户端默认值**（SQLAlchemy 在 INSERT 时补空串），
--   DDL 层只表达 NOT NULL，不声明 DEFAULT。该列因此也没有服务端默认值，非严格模式下
--   省略该列的写入会得到 '' / 告警，严格模式下会直接报错 —— 这正是「不让 NULL 混入」的本意。
--
-- 幂等：仅当列存在**且**当前 `IS_NULLABLE = 'YES'` 时才回填 + MODIFY；列已是 NOT NULL 时
--   整体跳过，二次执行不报错、不改语义、不额外全表扫描。列不存在时（未执行 016）同样跳过，
--   避免 MODIFY COLUMN 直接报错。
-- 不改历史迁移文件 016（迁移文件只前进不回头改）。

SET @characters_voice_description_nullable = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'characters'
    AND COLUMN_NAME = 'voice_description'
    AND IS_NULLABLE = 'YES'
);

-- 收紧前先回填历史 NULL（列若已是 NOT NULL 则不可能存在 NULL，跳过即可）。
SET @backfill_characters_voice_description_not_null = IF(
  @characters_voice_description_nullable = 1,
  "UPDATE characters SET voice_description = '' WHERE voice_description IS NULL",
  'SELECT 1'
);
PREPARE stmt_backfill_characters_voice_description FROM @backfill_characters_voice_description_not_null;
EXECUTE stmt_backfill_characters_voice_description;
DEALLOCATE PREPARE stmt_backfill_characters_voice_description;

-- MODIFY 不带 COMMENT 会清空原有注释，因此这里显式重复列注释。
SET @tighten_characters_voice_description = IF(
  @characters_voice_description_nullable = 1,
  "ALTER TABLE characters MODIFY COLUMN voice_description TEXT NOT NULL COMMENT '角色音色描述（剧本提取产出：年龄段/声线/气质/语速等；用于配音选型参考）'",
  'SELECT 1'
);
PREPARE stmt_tighten_characters_voice_description FROM @tighten_characters_voice_description;
EXECUTE stmt_tighten_characters_voice_description;
DEALLOCATE PREPARE stmt_tighten_characters_voice_description;
