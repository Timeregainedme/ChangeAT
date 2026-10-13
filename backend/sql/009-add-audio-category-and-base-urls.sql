-- 009: 新增音频（audio）模型类别所需的供应商/设置字段。
--
-- 背景：接入优云智算「模型 API」的 IndexTTS 2.5 语音能力后，模型类别扩展为
-- text/image/video/audio。`models.category` 为 VARCHAR(16)，无需变更即可存放 'audio'。
--
-- 本次仅补齐两处结构：
--   1. providers.audio_base_url —— 音频能力可按供应商单独覆盖 Base URL；
--   2. model_settings.default_audio_model_id —— 全局默认音频模型。
--
-- 幂等：全部通过 information_schema 判断后再执行，可重复应用于已升级的旧库。

SET @has_providers_audio_base_url = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'providers'
    AND COLUMN_NAME = 'audio_base_url'
);

SET @add_providers_audio_base_url = IF(
  @has_providers_audio_base_url = 0,
  "ALTER TABLE providers ADD COLUMN audio_base_url VARCHAR(1024) NULL COMMENT '音频能力 API Base URL（可选覆盖）'",
  'SELECT 1'
);
PREPARE stmt_add_providers_audio_base_url FROM @add_providers_audio_base_url;
EXECUTE stmt_add_providers_audio_base_url;
DEALLOCATE PREPARE stmt_add_providers_audio_base_url;

SET @has_model_settings_default_audio_model_id = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'model_settings'
    AND COLUMN_NAME = 'default_audio_model_id'
);

SET @add_model_settings_default_audio_model_id = IF(
  @has_model_settings_default_audio_model_id = 0,
  "ALTER TABLE model_settings ADD COLUMN default_audio_model_id VARCHAR(64) NULL COMMENT '默认音频模型 ID', ADD CONSTRAINT fk_model_settings_default_audio_model_id FOREIGN KEY (default_audio_model_id) REFERENCES models(id) ON DELETE SET NULL",
  'SELECT 1'
);
PREPARE stmt_add_model_settings_default_audio_model_id FROM @add_model_settings_default_audio_model_id;
EXECUTE stmt_add_model_settings_default_audio_model_id;
DEALLOCATE PREPARE stmt_add_model_settings_default_audio_model_id;

-- 兜底：确保单例设置行存在（006 已建，此处防御性重放）。
INSERT INTO model_settings (id, api_timeout, log_level)
SELECT 1, 30, 'info'
WHERE NOT EXISTS (SELECT 1 FROM model_settings WHERE id = 1);
