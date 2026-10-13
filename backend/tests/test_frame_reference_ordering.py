"""分镜帧参考图顺序测试 —— 提示词改造第 2 档 C3 + E 项。

C3：参考图任务强制让「角色卡」作 图1，锁住人物身份。
E ：内部统一「有序引用列表 + 图N」，视频侧再映射成 `<Picture N>`。

顺序由服务端决定（`derive_preview` 会据此重建 token 列表并把提示词里的实体名替换成
token），所以这里的排序契约必须锁住：角色 → 场景 → 道具 → 服装，同类内保持入参顺序，
重复 file_id 去重，无 file_id 的条目跳过，未识别类别排在最后且不丢弃。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.schemas.studio.shots import ShotLinkedAssetItem
from app.services.studio.generation.frame.build_context import (
    _reference_priority,
    build_ordered_shot_frame_references,
)


def _item(kind: str, *, item_id: str, file_id: str | None, name: str = "") -> ShotLinkedAssetItem:
    return ShotLinkedAssetItem(
        type=kind,
        id=item_id,
        file_id=file_id,
        name=name or item_id,
    )


def test_character_card_becomes_first_reference() -> None:
    """即使调用方把场景排在前面，角色卡也必须成为 图1。"""
    mappings = build_ordered_shot_frame_references(
        items=[
            _item("scene", item_id="scene-1", file_id="f-scene"),
            _item("character", item_id="char-1", file_id="f-char", name="林晚"),
        ]
    )
    assert [m.token for m in mappings] == ["图1", "图2"]
    assert mappings[0].type == "character"
    assert mappings[0].file_id == "f-char"
    assert mappings[0].name == "林晚"
    assert mappings[1].type == "scene"


def test_kind_priority_is_character_scene_prop_costume() -> None:
    mappings = build_ordered_shot_frame_references(
        items=[
            _item("costume", item_id="c-1", file_id="f-costume"),
            _item("prop", item_id="p-1", file_id="f-prop"),
            _item("scene", item_id="s-1", file_id="f-scene"),
            _item("character", item_id="h-1", file_id="f-char"),
        ]
    )
    assert [m.type for m in mappings] == ["character", "scene", "prop", "costume"]


def test_same_kind_keeps_caller_order() -> None:
    """稳定排序：同类内不得重排，否则用户在界面里调的顺序会被吞掉。"""
    mappings = build_ordered_shot_frame_references(
        items=[
            _item("character", item_id="char-2", file_id="f-2"),
            _item("character", item_id="char-1", file_id="f-1"),
        ]
    )
    assert [m.id for m in mappings] == ["char-2", "char-1"]


def test_duplicate_file_id_is_deduplicated() -> None:
    mappings = build_ordered_shot_frame_references(
        items=[
            _item("character", item_id="char-1", file_id="f-same"),
            _item("scene", item_id="scene-1", file_id="f-same"),
            _item("prop", item_id="prop-1", file_id="f-other"),
        ]
    )
    assert [m.file_id for m in mappings] == ["f-same", "f-other"]
    assert [m.token for m in mappings] == ["图1", "图2"]


def test_items_without_file_id_are_skipped() -> None:
    mappings = build_ordered_shot_frame_references(
        items=[
            _item("character", item_id="char-1", file_id=None),
            _item("scene", item_id="scene-1", file_id="f-scene"),
        ]
    )
    assert [m.file_id for m in mappings] == ["f-scene"]
    assert mappings[0].token == "图1"


def test_unknown_kind_is_kept_last_not_dropped() -> None:
    """`ShotLinkedAssetType` 目前只有 4 个取值，但排序函数对未知类别必须保守（不丢弃、排最后）。

    直接测优先级函数：靠 Schema 造不出第 5 种类别。
    """
    assert _reference_priority(SimpleNamespace(type="vehicle")) == 99
    assert _reference_priority(SimpleNamespace(type="  CHARACTER  ")) == 0
    assert _reference_priority(SimpleNamespace(type=None)) == 99


def test_empty_items_produce_no_references() -> None:
    assert build_ordered_shot_frame_references(items=[]) == []
