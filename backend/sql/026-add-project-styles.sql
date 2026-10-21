-- 风格目录：把「真人都市 / 真人科幻 / …」从枚举升级为可维护的表。
--
-- 为什么要表：业务上会持续出现新题材、新画风（例如「赛博国风」「黏土定格」），
-- 用枚举意味着每加一个风格都要改代码、发版、回归。
--
-- 迁移策略：建表后由后端在首次访问时用内置枚举做种子（见 style_catalog.ensure_style_catalog），
-- 因此本脚本不插入数据，避免与代码里的种子逻辑重复、也避免后续改种子时两边不一致。
CREATE TABLE IF NOT EXISTS project_styles (
  id            VARCHAR(64)  NOT NULL COMMENT '风格 ID',
  visual_style  VARCHAR(16)  NOT NULL COMMENT '所属画面表现形式（现实/动漫…）',
  name          VARCHAR(64)  NOT NULL COMMENT '风格名称',
  description   TEXT         NOT NULL COMMENT '面向用户的说明',
  sort_order    INT          NOT NULL DEFAULT 0 COMMENT '同组内排序',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_project_styles_visual_name (visual_style, name),
  KEY ix_project_styles_visual_style (visual_style)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='项目风格目录（可增删改）';
