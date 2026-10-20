-- 020-add-project-dialog-audio-reference.sql
--
-- 给项目增加「视频生成时是否自动带上台词配音作为参考音频」的开关。
--
-- 背景：
--   MiniMax H3 支持 reference_audio（≤3 个、必须同时有参考图）。
--   Jellyfish 会把镜头下已生成的台词配音自动作为参考音频提交，
--   但不同项目偏好不同（有些项目只想用纯画面参考，避免音色干扰画面生成），
--   因此在项目级提供开关，而不是全局硬编码。
--
-- 默认 1（开启）：保持本次上线的既有行为。

ALTER TABLE `projects`
  ADD COLUMN `use_dialog_audio_as_reference` TINYINT(1) NOT NULL DEFAULT 1
  COMMENT '视频生成时是否自动带上镜头台词已生成的配音作为参考音频（1=使用 0=不使用）';
