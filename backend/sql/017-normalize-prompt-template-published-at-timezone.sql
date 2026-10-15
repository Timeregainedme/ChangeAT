-- 017: 统一 prompt_templates.published_at 的时区口径（DATETIME -> DATETIME(6)）
--
-- 背景（评审 D-5）：
--   1) `prompt_templates.published_at` 由 015 以 `DATETIME` 建列，而
--      `PromptTemplate` 模型写入的是 `datetime.now(UTC)`（带 tzinfo 的 UTC 时刻）。
--      MySQL DATETIME 不保存时区，pymysql 会按**连接会话时区**把 aware datetime
--      转成墙钟字符串，而 DATETIME 列不携带 tzinfo，读回来就成了与 UTC 无关的
--      naive 值 —— 与同表 `created_at` / `updated_at`（`DateTime(timezone=True)`，
--      服务端 `NOW()` = 会话时区墙钟）口径不一致，同一行的两个时间可相差 8 小时
--      （worker 侧 `celery_app.py` 配置 `Asia/Shanghai`）。
--   2) 原列精度为秒，`datetime.now(UTC)` 的微秒被静默截断。
--
-- 修复口径：列类型统一为 `DATETIME(6)`（与 SQLAlchemy `DateTime(timezone=True)`
-- 在 MySQL 上的实际类型一致），并把写入值的语义固定为「UTC 墙钟」。
-- 读取路径（`prompt_registry`）只判断 `published_at IS NOT NULL` 与相对排序，
-- 不依赖绝对时区偏移，因此历史行无需回填 —— 回填反而会破坏「已发布」语义。
--
-- 幂等：本文件只做无条件 `MODIFY COLUMN`（把列改为目标形态是幂等的：
-- 第二次执行仍是同一形态，不报错、不改数据），可被 compose 重复执行。
-- 不改历史迁移文件 015（迁移文件只前进不回头改）。

ALTER TABLE `prompt_templates`
  MODIFY COLUMN `published_at` DATETIME(6) NULL
  COMMENT '发布时间（非空 = 已发布到运行时；仅 agent_* 分类使用，见 prompt_registry）。写入值统一为 UTC，列精度到微秒';
