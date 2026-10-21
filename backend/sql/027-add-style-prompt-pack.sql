-- 风格目录新增「提示词质感描述」。
--
-- 背景：自定义风格此前在出图时只会套用内置的「真人都市」描述，
-- 等于新风格只改了名字、没改画风。加这一列后，风格可以自带质感词，
-- 由生成链路注入到 asset/character 的提示词里。
--
-- 内置风格的初始值由后端种子逻辑写入（STYLE_PACKS），本脚本只加列。
SET @ddl = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'project_styles'
        AND COLUMN_NAME = 'prompt_pack'
    ),
    'SELECT 1',
    'ALTER TABLE project_styles ADD COLUMN prompt_pack TEXT NOT NULL COMMENT ''提示词质感描述'' AFTER description'
  )
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
