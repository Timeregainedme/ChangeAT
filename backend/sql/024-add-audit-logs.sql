-- 024-add-audit-logs.sql
--
-- 新增操作审计表，只追加不更新（见 app/models/audit.py 的设计说明）。
--
-- 幂等性：见 022 文件头，本脚本可重复执行。

BEGIN;

CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '记录 ID',
  `workspace_id` VARCHAR(64) NULL COMMENT '所属工作区（可空：未进入租户上下文即失败）',
  `user_id` INT NULL COMMENT '操作账号（可空：未认证或凭证无效）',
  `action` VARCHAR(32) NOT NULL COMMENT '动作类型：create/update/delete/other',
  `method` VARCHAR(8) NOT NULL COMMENT 'HTTP 方法',
  `path` VARCHAR(512) NOT NULL COMMENT '请求路径（不含 query）',
  `resource_type` VARCHAR(64) NULL COMMENT '资源类型（由路径推断）',
  `resource_id` VARCHAR(64) NULL COMMENT '资源 ID（由路径末段推断）',
  `status_code` INT NOT NULL COMMENT '响应状态码',
  `duration_ms` INT NOT NULL COMMENT '耗时（毫秒）',
  `ip` VARCHAR(64) NULL COMMENT '客户端 IP',
  `user_agent` VARCHAR(256) NULL COMMENT 'User-Agent',
  `request_id` VARCHAR(64) NULL COMMENT '请求 ID',
  `detail` TEXT NULL COMMENT '补充说明（不含敏感内容）',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_audit_logs_created_at` (`created_at`),
  KEY `ix_audit_logs_ws_created` (`workspace_id`, `created_at`),
  KEY `ix_audit_logs_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作审计日志';

COMMIT;
