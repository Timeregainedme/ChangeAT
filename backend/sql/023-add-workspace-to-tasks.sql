-- 023-add-workspace-to-tasks.sql
--
-- 给 generation_tasks 增加工作区归属，补齐任务相关接口的租户隔离。
--
-- 为什么任务表必须独立持有 workspace_id（不能像章节/镜头那样经 project 归属）：
--   1. 一次任务可能产出多个资源、跨多个项目（例如批量资产图任务），
--      没有唯一的父 project 可回溯；
--   2. 任务关联走 `generation_task_links` 的多态字段
--      （resource_type + relation_type + relation_entity_id），
--      反查需要先解析 relation_type 才能知道去查哪张表，无法用于鉴权；
--   3. 任务列表/状态/取消是高频只读接口，鉴权路径必须是一次主键查询。
--
-- 为什么 NOT NULL：
--   漏传 workspace_id 时希望直接失败，而不是产生「所有租户都能看到」的匿名任务。
--   存量任务统一回填到默认工作区 `ws-default`（多租户改造前没有租户概念，
--   这些任务属于改造前的唯一团队）。
--
-- 幂等性：见 022 文件头说明，本脚本同样必须可重复执行。

BEGIN;

-- ========== 0. 前置：确保 workspaces 存在 ==========
-- 022 负责建表；这里若发现表缺失说明迁移顺序被破坏，直接报错比静默继续安全。
SET @has_ws_table = (
  SELECT COUNT(*) FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'workspaces'
);
SET @sql = IF(
  @has_ws_table = 0,
  'SELECT ''ERROR: workspaces 表不存在，请先执行 sql/022-add-workspaces.sql''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ========== 1. 加列（先可空，便于回填） ==========
SET @has_ws_col = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'generation_tasks' AND COLUMN_NAME = 'workspace_id'
);
SET @sql = IF(
  @has_ws_col = 0,
  'ALTER TABLE `generation_tasks` ADD COLUMN `workspace_id` VARCHAR(64) NULL COMMENT ''所属工作区（多租户边界）''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ========== 2. 回填存量任务 ==========
-- 改造前的任务没有租户归属，统一挂默认工作区；若默认工作区不存在（空库），跳过。
SET @has_default_ws = (SELECT COUNT(*) FROM `workspaces` WHERE `id` = 'ws-default');
UPDATE `generation_tasks`
SET `workspace_id` = 'ws-default'
WHERE `workspace_id` IS NULL AND @has_default_ws > 0;

-- ========== 3. 收紧为 NOT NULL ==========
-- 仅当没有 NULL 残留时收紧；否则保持可空并留待人工处理，
-- 避免迁移在启动流程里抛错导致整条 compose 起不来。
SET @null_cnt = (SELECT COUNT(*) FROM `generation_tasks` WHERE `workspace_id` IS NULL);
SET @is_nullable = (
  SELECT IS_NULLABLE FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'generation_tasks' AND COLUMN_NAME = 'workspace_id'
);
SET @sql = IF(
  @null_cnt = 0 AND @is_nullable = 'YES',
  'ALTER TABLE `generation_tasks` MODIFY COLUMN `workspace_id` VARCHAR(64) NOT NULL COMMENT ''所属工作区（多租户边界）''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ========== 4. 索引 ==========
SET @has_idx = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'generation_tasks' AND INDEX_NAME = 'ix_generation_tasks_workspace_id'
);
SET @sql = IF(
  @has_idx = 0,
  'ALTER TABLE `generation_tasks` ADD INDEX `ix_generation_tasks_workspace_id` (`workspace_id`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ========== 5. 外键 ==========
SET @has_fk = (
  SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'generation_tasks'
    AND COLUMN_NAME = 'workspace_id'
    AND REFERENCED_TABLE_NAME = 'workspaces'
);
SET @sql = IF(
  @has_fk = 0,
  'ALTER TABLE `generation_tasks` ADD CONSTRAINT `fk_generation_tasks_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE RESTRICT',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

COMMIT;
