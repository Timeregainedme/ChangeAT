-- 021-add-google-oauth.sql
--
-- 给 users 增加 Google 登录所需字段，并允许「没有密码」的账号存在。
--
-- 背景：
--   Google 登录使用 Google Identity Services 在前端拿到 ID Token，
--   后端校验后按 email / google_sub 找到或创建账号。
--   这类账号没有本地密码，因此 password_hash 必须允许 NULL；
--   本地账号密码登录在 password_hash 为 NULL 时直接拒绝（见 auth 路由）。
--
-- 兼容性：
--   - 原有 admin 账号不受影响（password_hash 保持原值，auth_provider 默认 local）；
--   - email / google_sub 均可空，且各自唯一（MySQL 唯一索引允许多个 NULL）。

ALTER TABLE `users`
  MODIFY COLUMN `password_hash` VARCHAR(255) NULL
    COMMENT 'bcrypt 哈希；仅本地账号有值，Google 账号为 NULL';

ALTER TABLE `users`
  ADD COLUMN `email` VARCHAR(255) NULL COMMENT '邮箱（Google 登录按此匹配/创建账号）',
  ADD COLUMN `google_sub` VARCHAR(64) NULL COMMENT 'Google 用户唯一标识（sub）',
  ADD COLUMN `avatar_url` VARCHAR(512) NULL COMMENT '头像 URL（来自 Google profile）',
  ADD COLUMN `auth_provider` VARCHAR(16) NOT NULL DEFAULT 'local'
    COMMENT '账号来源：local=本地密码，google=Google 登录';

ALTER TABLE `users`
  ADD UNIQUE KEY `uq_users_email` (`email`),
  ADD UNIQUE KEY `uq_users_google_sub` (`google_sub`);
