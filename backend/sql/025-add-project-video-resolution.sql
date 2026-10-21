-- 项目级默认视频分辨率档位（768p / 2k）。
--
-- 与 default_image_resolution_profile 对称：只存档位字符串，
-- 具体可用值由供应商能力（video_capabilities）决定，不在库里枚举。
-- 幂等：重复执行不会报错。
SET @ddl = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'projects'
        AND COLUMN_NAME = 'default_video_resolution'
    ),
    'SELECT 1',
    'ALTER TABLE projects ADD COLUMN default_video_resolution VARCHAR(16) NULL COMMENT ''项目级默认视频分辨率档位（如 768p/2k）'' AFTER default_image_resolution_profile'
  )
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
