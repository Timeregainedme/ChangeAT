"""校验 `backend/sql/015-add-agent-prompt-templates.sql` 与代码默认提示词逐字一致。

为什么需要它：
- 015 由 `gen_agent_prompt_templates_sql.py` 生成，权威文本是 `app/chains/agents/*.py`
  里的 `_*_SYSTEM_PROMPT` 常量；一旦有人只改代码不改 SQL，用户打开模板页
  不改内容直接点「发布生效」就会把**旧提示词**写进运行时（评审 B-5）。
- 本脚本不写文件，只做比对：解析 015 中的 UPDATE 语句，还原被转义的内容，
  再与生成器内存中的 `AGENT_TEMPLATES` 逐字比对。

用法：cd backend && uv run python scripts/check_agent_prompt_templates_sql.py
退出码：0 = 完全一致；1 = 存在差异或解析失败（可直接挂进 CI）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from scripts.gen_agent_prompt_templates_sql import AGENT_TEMPLATES  # noqa: E402

# 生成器的输出路径（与 gen_agent_prompt_templates_sql.main 保持一致）
SQL_PATH = BACKEND_DIR / "sql" / "015-add-agent-prompt-templates.sql"

# 生成器写出的 UPDATE 形态固定，这里按同一形态解析：
# UPDATE `prompt_templates` SET `name` = '<n>', `preview` = '<p>', `content` = '<c>', ...
_UPDATE_RE = re.compile(
    r"UPDATE `prompt_templates` SET `name` = '(?P<name>(?:[^']|'')*)', "
    r"`preview` = '(?P<preview>(?:[^']|'')*)', "
    r"`content` = '(?P<content>(?:[^']|'')*)', "
    r"`is_default` = 0, `is_system` = 0, `updated_at` = NOW\(\) "
    r"WHERE `category` = '(?P<category>[^']+)';",
    re.DOTALL,
)


def _unescape(value: str) -> str:
    """还原 `_sql_escape`：'' -> '、\\\\ -> \\。"""
    return value.replace("\\\\", "\\").replace("''", "'")


def _parse_sql_updates(text: str) -> dict[str, tuple[str, str, str]]:
    """解析 SQL 中每个 category 的 (name, preview, content)。"""
    parsed: dict[str, tuple[str, str, str]] = {}
    for match in _UPDATE_RE.finditer(text):
        category = match.group("category")
        parsed[category] = (
            _unescape(match.group("name")),
            _unescape(match.group("preview")),
            _unescape(match.group("content")),
        )
    return parsed


def main() -> int:
    sql_text = SQL_PATH.read_text(encoding="utf-8")
    parsed = _parse_sql_updates(sql_text)

    problems: list[str] = []

    missing = sorted(set(AGENT_TEMPLATES) - set(parsed))
    extra = sorted(set(parsed) - set(AGENT_TEMPLATES))
    if missing:
        problems.append(f"SQL 缺失分类: {missing}")
    if extra:
        problems.append(f"SQL 多出分类: {extra}")

    for category, (name, preview, content) in AGENT_TEMPLATES.items():
        if category not in parsed:
            continue
        sql_name, sql_preview, sql_content = parsed[category]
        if (sql_name, sql_preview) != (name, preview):
            problems.append(f"{category}: name/preview 不一致")
        if sql_content != content:
            problems.append(f"{category}: content 与代码默认不一致")

    print(f"sql file        : {SQL_PATH}")
    print(f"templates(code) : {len(AGENT_TEMPLATES)}")
    print(f"templates(sql)  : {len(parsed)}")
    print(f"EXACT_MATCH: {not problems}")
    for item in problems:
        print(f"  - {item}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
