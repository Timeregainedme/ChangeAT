"""生成 `backend/sql/015-add-agent-prompt-templates.sql`。

为什么生成而不是手写：
- Agent 系统提示词的权威文本在 `app/chains/agents/*.py` 的各 `_*_SYSTEM_PROMPT` 常量里，
  手抄一份进 SQL 必然漂移；这里直接 import 常量，保证 SQL 与代码逐字一致。

生成内容：
1. `prompt_templates.published_at` 列（幂等：information_schema 判断后才 ALTER）；
2. 12 条 agent_* 分类种子模板（同 category 已存在则 UPDATE，不存在则 INSERT）。

语义约定：
- `is_system = 0`：agent 模板允许编辑（用户需在模板页修改后手动「发布生效」）；
- `published_at = NULL`：默认未发布，运行时使用代码内置默认提示词；
- 发布状态由 `published_at` 表达，与 `is_default`（生成类模板的默认选择）解耦。

用法：cd backend && .venv/bin/python scripts/gen_agent_prompt_templates_sql.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.chains.agents import (  # noqa: E402
    character_portrait_analysis_agent,
    consistency_checker_agent,
    costume_info_analysis_agent,
    element_extractor_agent,
    entity_merger_agent,
    h3_video_prompt_agent,
    prop_info_analysis_agent,
    scene_info_analysis_agent,
    script_divider_agent,
    script_optimizer_agent,
    script_simplifier_agent,
    variant_analyzer_agent,
)

# category -> (name, preview, content)
AGENT_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "agent_script_division": (
        "分镜拆解提示词",
        "剧本分镜 Agent 系统提示词（发布后生效）",
        script_divider_agent._SCRIPT_DIVIDER_SYSTEM_PROMPT,
    ),
    "agent_element_extract": (
        "要素提取提示词",
        "剧本要素提取 Agent 系统提示词（发布后生效）",
        element_extractor_agent._SCRIPT_EXTRACTOR_SYSTEM_PROMPT,
    ),
    "agent_character_portrait": (
        "角色画像提示词",
        "角色画像分析 Agent 系统提示词（发布后生效）",
        character_portrait_analysis_agent._CHARACTER_PORTRAIT_SYSTEM_PROMPT,
    ),
    "agent_scene_info": (
        "场景信息提示词",
        "场景信息分析 Agent 系统提示词（发布后生效）",
        scene_info_analysis_agent._SCENE_INFO_SYSTEM_PROMPT,
    ),
    "agent_prop_info": (
        "道具信息提示词",
        "道具信息分析 Agent 系统提示词（发布后生效）",
        prop_info_analysis_agent._PROP_INFO_SYSTEM_PROMPT,
    ),
    "agent_costume_info": (
        "服装信息提示词",
        "服装信息分析 Agent 系统提示词（发布后生效）",
        costume_info_analysis_agent._COSTUME_INFO_SYSTEM_PROMPT,
    ),
    "agent_consistency_check": (
        "一致性检查提示词",
        "一致性检查 Agent 系统提示词（发布后生效）",
        consistency_checker_agent._CONSISTENCY_CHECKER_SYSTEM_PROMPT,
    ),
    "agent_entity_merge": (
        "实体合并提示词",
        "实体合并 Agent 系统提示词（发布后生效）",
        entity_merger_agent._ENTITY_MERGER_SYSTEM_PROMPT,
    ),
    "agent_script_optimize": (
        "剧本优化提示词",
        "剧本优化 Agent 系统提示词（发布后生效）",
        script_optimizer_agent._SCRIPT_OPTIMIZER_SYSTEM_PROMPT,
    ),
    "agent_script_simplify": (
        "剧本简化提示词",
        "剧本简化 Agent 系统提示词（发布后生效）",
        script_simplifier_agent._SCRIPT_SIMPLIFIER_SYSTEM_PROMPT,
    ),
    "agent_variant_analyze": (
        "变体分析提示词",
        "变体分析 Agent 系统提示词（发布后生效）",
        variant_analyzer_agent._VARIANT_ANALYZER_SYSTEM_PROMPT,
    ),
    "agent_h3_video": (
        "H3 视频提示词",
        "MiniMax H3 英文正文 Agent 系统提示词（发布后生效）",
        h3_video_prompt_agent._SYSTEM_PROMPT,
    ),
}


def _sql_escape(text: str) -> str:
    """MySQL 字符串转义：单引号翻倍。"""
    return text.replace("\\", "\\\\").replace("'", "''")


def _build_column_sql() -> str:
    return """-- 1) 增加 published_at 列（幂等）
SET @has_published_at = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'prompt_templates'
    AND COLUMN_NAME = 'published_at'
);
SET @add_published_at = IF(
  @has_published_at = 0,
  "ALTER TABLE prompt_templates ADD COLUMN published_at DATETIME NULL COMMENT '发布时间（非空 = 已发布到运行时；仅 agent_* 分类使用）' AFTER is_system",
  'SELECT 1'
);
PREPARE stmt_add_published_at FROM @add_published_at;
EXECUTE stmt_add_published_at;
DEALLOCATE PREPARE stmt_add_published_at;
"""


def _build_template_sql(category: str, name: str, preview: str, content: str) -> str:
    esc_name = _sql_escape(name)
    esc_preview = _sql_escape(preview)
    esc_content = _sql_escape(content)
    return f"""-- ===== {category} =====
UPDATE `prompt_templates` SET `name` = '{esc_name}', `preview` = '{esc_preview}', `content` = '{esc_content}', `is_default` = 0, `is_system` = 0, `updated_at` = NOW() WHERE `category` = '{category}';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `published_at`, `created_at`, `updated_at`) SELECT UUID(), '{category}', '{esc_name}', '{esc_preview}', '{esc_content}', CAST('[]' AS JSON), 0, 0, NULL, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = '{category}');"""


def main() -> None:
    lines = [
        "-- 015-add-agent-prompt-templates.sql",
        "-- Agent 系统提示词模板化：12 个运行时 Agent 的提示词进入模板表，可在模板页编辑并手动发布生效。",
        "-- 由 backend/scripts/gen_agent_prompt_templates_sql.py 生成，请勿手工编辑。",
        "-- 幂等：published_at 列经 information_schema 判断；模板按 category UPDATE/INSERT。",
        "-- 发布语义：published_at 非空 = 已发布；未发布时运行时使用代码内置默认提示词。",
        "",
        "SET NAMES utf8mb4;",
        "",
        _build_column_sql(),
        "",
    ]
    for category, (name, preview, content) in AGENT_TEMPLATES.items():
        lines.append(_build_template_sql(category, name, preview, content))
        lines.append("")

    out = Path(BACKEND_DIR) / "sql" / "015-add-agent-prompt-templates.sql"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {out} ({len(AGENT_TEMPLATES)} templates)")


if __name__ == "__main__":
    main()
