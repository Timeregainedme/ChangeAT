"""契约与 DDL 一致性单测：角色音色描述（评审 C-3 / D-9）。

为什么要这些测试：
- C-3：`CharacterUpdate` 曾漏声明 `voice_description`，导致 PATCH 改不了音色描述；
  ORM（`nullable=False, default=""`）与 DDL（016 建的是 `TEXT NULL`）口径也不一致，
  绕过 ORM 写入的 NULL 会让读取侧拿到 `None`。
- D-9：016 的注释把「BLOB/TEXT 不允许 DEFAULT」误写成 MySQL 5.7 独有限制，
  且回填 UPDATE 每次执行都全表扫描、缺少幂等守卫。

本文件只做静态/契约级断言（不依赖 MySQL），因为 SQL 幂等性无法在 sqlite 上实测。
"""

from __future__ import annotations

from pathlib import Path

from app.models.studio import Character
from app.schemas.studio.cast import CharacterUpdate

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def test_character_update_accepts_voice_description() -> None:
    """C-3：PATCH 请求体必须能携带音色描述（修复前该字段被 pydantic 静默丢弃）。"""
    payload = CharacterUpdate.model_validate({"voice_description": "青年女声，清亮温柔，语速偏快"})
    assert payload.model_dump(exclude_unset=True) == {"voice_description": "青年女声，清亮温柔，语速偏快"}


def test_character_update_voice_description_is_optional() -> None:
    """C-3：不传该字段时不得出现在 `exclude_unset` 结果中，避免 PATCH 误清空既有值。"""
    payload = CharacterUpdate.model_validate({"name": "小雨"})
    assert "voice_description" not in payload.model_dump(exclude_unset=True)


def test_character_update_still_has_other_patch_fields() -> None:
    """C-3 回归：补字段不应破坏原有可改字段集合。"""
    payload = CharacterUpdate.model_validate({"name": "小雨", "voice_id": "v1", "voice_description": "低沉男声"})
    assert set(payload.model_dump(exclude_unset=True)) == {"name", "voice_id", "voice_description"}


def test_orm_column_is_not_null_with_client_default() -> None:
    """C-3：ORM 口径 = NOT NULL + 客户端默认空串，且不依赖服务端 DEFAULT。

    为什么：MySQL 对 BLOB/TEXT 一律不允许 DEFAULT（D-9），所以 DDL 层无法表达 `TEXT DEFAULT ''`；
    空串必须由 SQLAlchemy 在 INSERT 时补，DDL 只负责 NOT NULL。
    """
    column = Character.__table__.c.voice_description
    assert column.nullable is False
    assert column.server_default is None
    assert column.default is not None
    assert column.default.arg == ""


def test_sql_migration_numbers_are_unique() -> None:
    """DDL 序号不得重复：新增迁移必须另起序号，而不是改写历史文件。"""
    numbers = [path.name.split("-", 1)[0] for path in SQL_DIR.glob("*.sql")]
    assert len(numbers) == len(set(numbers)), f"重复的迁移序号：{sorted(numbers)}"


def test_sql_016_comment_fixed_and_backfill_guarded() -> None:
    """D-9：注释措辞修正为 BLOB/TEXT 通用限制，回填 UPDATE 加幂等守卫。"""
    text = (SQL_DIR / "016-add-character-voice-description.sql").read_text(encoding="utf-8")
    # 措辞：不再把限制归因到 5.7
    assert "MySQL 5.7 不允许 TEXT 列带 DEFAULT" not in text
    assert "5.7 与 8.0 相同" in text
    # 幂等：回填不再是顶层裸语句，而是包在 PREPARE 守卫里，且以「本次刚建出该列」为条件
    assert "\nUPDATE characters SET voice_description" not in text
    assert "@has_characters_voice_description = 0" in text
    assert "PREPARE stmt_backfill_characters_voice_description FROM" in text
    # 不改列定义语义（016 仍建 NULL 列，收紧交给 018）
    assert "ADD COLUMN voice_description TEXT NULL" in text


def test_sql_018_tightens_column_to_not_null_idempotently() -> None:
    """C-3：新增 018 把列收紧为 NOT NULL，以 IS_NULLABLE 守卫保证可重复执行。"""
    text = (SQL_DIR / "018-unify-character-voice-description-not-null.sql").read_text(encoding="utf-8")
    assert "IS_NULLABLE = 'YES'" in text
    assert "MODIFY COLUMN voice_description TEXT NOT NULL" in text
    # 回填同样加守卫，不是顶层裸语句
    assert "\nUPDATE characters SET voice_description" not in text
    assert "PREPARE stmt_backfill_characters_voice_description FROM" in text
    # 顺序：必须先回填 NULL 再收紧，否则 ALTER 会因存量 NULL 失败
    assert text.index("UPDATE characters SET voice_description") < text.index(
        "MODIFY COLUMN voice_description"
    )
    # 不改历史迁移文件：016 保持原样即可，这里只断言 018 自身不做多余的事
    assert "ALTER TABLE characters ADD COLUMN" not in text
