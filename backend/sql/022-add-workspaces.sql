-- 022-add-workspaces.sql
--
-- Phase 1 / 多租户第一步：引入工作区（workspace）作为业务数据的顶层归属。
--
-- 为什么所有语句都必须幂等：
--   compose 的启动顺序是 backend-init-db（SQLAlchemy create_all）→ mysql-init-sql
--   （按文件名排序 apply 本目录全部 SQL）。因此在全新库上，create_all 已经按
--   models 建好了 workspaces / workspace_members 与 projects.workspace_id，
--   本脚本再执行 CREATE/ALTER 会撞「已存在」。参见 002 迁移开头的同类说明。
--   对存量库，create_all 不会补表也不加列，必须靠本脚本补齐。
--   两种场景都要能跑通，所以：建表用 IF NOT EXISTS，加列/加索引用
--   information_schema 判断，回填用 INSERT IGNORE。
--
-- 回填策略（存量数据不丢访问权）：
--   1. 建一个默认工作区 `ws-default`，owner 取最早创建的账号；
--   2. 既有用户全部加为成员，owner 账号保留 owner 角色，其余给 editor
--      —— 宁可多给权限也不能让现有用户登录后看不到自己的项目；
--   3. 全部存量项目挂到 `ws-default`。
--   库为空（没有 users）时，第 1 步不插入，后续步骤因外键/条件自动跳过。

BEGIN;

-- ========== 1. workspaces ==========
CREATE TABLE IF NOT EXISTS `workspaces` (
  `id` VARCHAR(64) NOT NULL COMMENT '工作区 ID',
  `name` VARCHAR(128) NOT NULL COMMENT '工作区名称',
  `slug` VARCHAR(64) NOT NULL COMMENT 'URL 友好标识（唯一）',
  `description` TEXT NOT NULL COMMENT '工作区简介',
  `owner_id` INT NOT NULL COMMENT '所有者（创建者）',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用（停用工作区不删数据）',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workspaces_slug` (`slug`),
  KEY `ix_workspaces_owner_id` (`owner_id`),
  CONSTRAINT `fk_workspaces_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工作区（租户）';

-- ========== 2. workspace_members ==========
CREATE TABLE IF NOT EXISTS `workspace_members` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '成员记录 ID',
  `workspace_id` VARCHAR(64) NOT NULL COMMENT '所属工作区',
  `user_id` INT NOT NULL COMMENT '成员账号',
  `role` VARCHAR(16) NOT NULL DEFAULT 'editor' COMMENT '角色：owner/admin/editor/viewer',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否为在岗成员',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workspace_members_ws_user` (`workspace_id`, `user_id`),
  KEY `ix_workspace_members_user_id` (`user_id`),
  CONSTRAINT `fk_workspace_members_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_workspace_members_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工作区成员与角色';

-- ========== 3. projects 增加归属列 ==========
-- 先加可空列：存量行此时还没有合法 workspace_id，直接 NOT NULL 会失败。
SET @has_ws_col = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'workspace_id'
);
SET @sql = IF(
  @has_ws_col = 0,
  'ALTER TABLE `projects` ADD COLUMN `workspace_id` VARCHAR(64) NULL COMMENT ''所属工作区（多租户边界）''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_creator_col = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'created_by'
);
SET @sql = IF(
  @has_creator_col = 0,
  'ALTER TABLE `projects` ADD COLUMN `created_by` INT NULL COMMENT ''创建者账号（账号删除后置空，项目保留）''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ========== 4. 建立默认工作区 ==========
-- INSERT IGNORE 依赖主键 `id`，重复执行时静默跳过。
-- 派生表 u 取最早账号；users 为空时子查询返回 NULL，WHERE 直接过滤掉。
INSERT IGNORE INTO `workspaces`
  (`id`, `name`, `slug`, `description`, `owner_id`, `is_active`, `created_at`, `updated_at`)
SELECT
  'ws-default',
  '默认工作区',
  'default',
  '系统自动创建：承接多租户改造前的全部项目与成员',
  u.`min_id`,
  1,
  NOW(),
  NOW()
FROM (SELECT MIN(`id`) AS `min_id` FROM `users`) AS u
WHERE u.`min_id` IS NOT NULL;

-- ========== 5. 回填成员 ==========
-- owner 账号保持 owner，其余既有用户给 editor（宁可宽，不可让存量用户失去访问权）。
INSERT IGNORE INTO `workspace_members`
  (`workspace_id`, `user_id`, `role`, `is_active`, `created_at`, `updated_at`)
SELECT
  'ws-default',
  u.`id`,
  CASE
    WHEN u.`id` = (SELECT `owner_id` FROM `workspaces` WHERE `id` = 'ws-default') THEN 'owner'
    ELSE 'editor'
  END,
  1,
  NOW(),
  NOW()
FROM `users` AS u
WHERE EXISTS (SELECT 1 FROM `workspaces` WHERE `id` = 'ws-default');

-- ========== 6. 回填 projects.workspace_id ==========
SET @has_default_ws = (SELECT COUNT(*) FROM `workspaces` WHERE `id` = 'ws-default');
UPDATE `projects`
SET `workspace_id` = 'ws-default'
WHERE `workspace_id` IS NULL AND @has_default_ws > 0;

-- ========== 7. 收紧为 NOT NULL ==========
-- 只有确认没有 NULL 残留时才收紧；否则宁可保持可空并留待人工处理，
-- 也不要在启动流程里抛错导致整条 compose 起不来。
SET @null_ws_cnt = (SELECT COUNT(*) FROM `projects` WHERE `workspace_id` IS NULL);
SET @ws_nullable = (
  SELECT IS_NULLABLE FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'workspace_id'
);
SET @sql = IF(
  @null_ws_cnt = 0 AND @ws_nullable = 'YES',
  'ALTER TABLE `projects` MODIFY COLUMN `workspace_id` VARCHAR(64) NOT NULL COMMENT ''所属工作区（多租户边界）''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ========== 8. 索引与外键 ==========
SET @has_ws_idx = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND INDEX_NAME = 'ix_projects_workspace_id'
);
SET @sql = IF(
  @has_ws_idx = 0,
  'ALTER TABLE `projects` ADD INDEX `ix_projects_workspace_id` (`workspace_id`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_creator_idx = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND INDEX_NAME = 'ix_projects_created_by'
);
SET @sql = IF(
  @has_creator_idx = 0,
  'ALTER TABLE `projects` ADD INDEX `ix_projects_created_by` (`created_by`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 外键按「是否已有引用 workspaces 的约束」判断，不锁死约束名：
-- create_all 自动生成的约束名与本脚本不同，按名字判断会重复创建。
SET @has_ws_fk = (
  SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'projects'
    AND COLUMN_NAME = 'workspace_id'
    AND REFERENCED_TABLE_NAME = 'workspaces'
);
SET @sql = IF(
  @has_ws_fk = 0,
  'ALTER TABLE `projects` ADD CONSTRAINT `fk_projects_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE RESTRICT',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_creator_fk = (
  SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'projects'
    AND COLUMN_NAME = 'created_by'
    AND REFERENCED_TABLE_NAME = 'users'
);
SET @sql = IF(
  @has_creator_fk = 0,
  'ALTER TABLE `projects` ADD CONSTRAINT `fk_projects_created_by` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

COMMIT;
