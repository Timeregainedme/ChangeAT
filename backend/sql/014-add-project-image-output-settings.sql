-- 014: 项目级图片输出设置（比例 + 分辨率档位）
--
-- 背景（用户开工预检第 ⑤ 项的缺口）：
--   开工前必须能确认「短剧风格与分辨率、图片格式」，但此前：
--     - `projects` 只有 `default_video_ratio`，没有任何图片输出设置；
--     - 关键帧的 `resolution_profile`（standard/high，PIX 映射为 1K/2K）只存在于
--       前端 state（`ChapterStudio.tsx` 的 `keyframeResolutionProfile`），从未落库；
--     - 因此 `GET /projects/{id}/production-readiness` 无法检查图片输出规格，
--       用户只能等到真正跑图才发现档位/比例不对。
--
-- 落点（与既有 default_video_ratio 同构，均可为空）：
--   - projects.default_image_ratio              图片默认比例（为空时回落到 default_video_ratio）
--   - projects.default_image_resolution_profile 图片分辨率档位（为空时回落到提供方默认档位）
--
-- 幂等：全部通过 information_schema 判定后再 ALTER，可被 compose 重复执行。

-- 1) projects.default_image_ratio
SET @has_projects_default_image_ratio = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'projects'
    AND COLUMN_NAME = 'default_image_ratio'
);

SET @add_projects_default_image_ratio = IF(
  @has_projects_default_image_ratio = 0,
  "ALTER TABLE projects ADD COLUMN default_image_ratio VARCHAR(16) NULL COMMENT '项目级默认图片比例（可为空；为空时回落到 default_video_ratio）'",
  'SELECT 1'
);
PREPARE stmt_add_projects_default_image_ratio FROM @add_projects_default_image_ratio;
EXECUTE stmt_add_projects_default_image_ratio;
DEALLOCATE PREPARE stmt_add_projects_default_image_ratio;

-- 2) projects.default_image_resolution_profile
SET @has_projects_default_image_resolution_profile = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'projects'
    AND COLUMN_NAME = 'default_image_resolution_profile'
);

SET @add_projects_default_image_resolution_profile = IF(
  @has_projects_default_image_resolution_profile = 0,
  "ALTER TABLE projects ADD COLUMN default_image_resolution_profile VARCHAR(16) NULL COMMENT '项目级默认图片分辨率档位（standard/high；为空时回落到提供方默认档位）'",
  'SELECT 1'
);
PREPARE stmt_add_projects_default_image_resolution_profile FROM @add_projects_default_image_resolution_profile;
EXECUTE stmt_add_projects_default_image_resolution_profile;
DEALLOCATE PREPARE stmt_add_projects_default_image_resolution_profile;
