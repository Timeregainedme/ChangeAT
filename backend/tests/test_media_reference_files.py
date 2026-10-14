"""参考素材「引用存储、派发期物化」的回归测试。

守护的核心性质：写进 `generation_tasks.payload` 的 run_args 永远只含 file_id，
不含内联 base64——base64 一旦入库，会让 MySQL 在默认 sort_buffer_size 下对含
`generation_tasks` 的排序直接报 1038。
"""

from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from app.services import media_reference_files as mrf

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")


class _FakeFileItem:
    def __init__(self, *, storage_key: str) -> None:
        self.storage_key = storage_key


class _FakeInfo:
    def __init__(self, content_type: str) -> None:
        self.content_type = content_type


class _FakeSession:
    """只实现被测代码用到的 `db.get`。"""

    def __init__(self, rows: dict[str, object]) -> None:
        self._rows = rows

    async def get(self, _model: object, key: str) -> object:
        return self._rows.get(key)


class _FakeStorage:
    def __init__(self, *, content_type: str = "image/png") -> None:
        self.content_type = content_type

    async def get_file_info(self, *, key: str) -> _FakeInfo:
        return _FakeInfo(self.content_type)

    async def download_file(self, *, key: str) -> bytes:
        return PNG_BYTES


@pytest.fixture
def db() -> _FakeSession:
    return _FakeSession(
        {
            "img-1": _FakeFileItem(storage_key="files/img-1.png"),
            "img-2": _FakeFileItem(storage_key="files/img-2.png"),
            "not-an-image": _FakeFileItem(storage_key="files/doc.txt"),
            "no-storage-key": _FakeFileItem(storage_key=""),
        }
    )


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mrf, "storage", _FakeStorage())


@pytest.mark.asyncio
async def test_compact_refs_keep_only_file_ids(db: _FakeSession) -> None:
    """写入 payload 的形状：只有 id，没有字节。"""
    refs = await mrf.compact_image_reference_refs(db, file_ids=["img-1", "img-2"])

    assert refs == [{"file_id": "img-1"}, {"file_id": "img-2"}]
    assert "base64" not in repr(refs)


@pytest.mark.asyncio
async def test_compact_refs_skip_blank_entries(db: _FakeSession) -> None:
    refs = await mrf.compact_image_reference_refs(db, file_ids=["", "  ", "img-1"])

    assert refs == [{"file_id": "img-1"}]


@pytest.mark.asyncio
async def test_materialize_turns_file_id_into_data_url(db: _FakeSession) -> None:
    materialized = await mrf.materialize_image_reference_refs(
        db,
        images=[{"file_id": "img-1"}],
    )

    assert materialized == [{"image_url": PNG_DATA_URL}]


@pytest.mark.asyncio
async def test_materialize_passes_through_existing_image_url(db: _FakeSession) -> None:
    """历史 payload（已内联 base64）必须原样可跑。"""
    legacy = [{"image_url": "data:image/png;base64,AAA"}]

    assert await mrf.materialize_image_reference_refs(db, images=legacy) == legacy


@pytest.mark.asyncio
async def test_materialize_mixed_refs_preserve_order(db: _FakeSession) -> None:
    materialized = await mrf.materialize_image_reference_refs(
        db,
        images=[{"file_id": "img-1"}, {"image_url": "data:image/png;base64,AAA"}],
    )

    assert materialized == [{"image_url": PNG_DATA_URL}, {"image_url": "data:image/png;base64,AAA"}]


@pytest.mark.asyncio
async def test_materialize_file_ids_returns_data_urls_in_order(db: _FakeSession) -> None:
    urls = await mrf.materialize_file_ids(db, file_ids=["img-1", "img-2"])

    assert urls == [PNG_DATA_URL, PNG_DATA_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_file_id", ["missing", "no-storage-key"])
async def test_assert_rejects_unusable_file_id(db: _FakeSession, bad_file_id: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await mrf.assert_reference_image_file_id(db, file_id=bad_file_id)

    assert exc_info.value.status_code == 400
    assert bad_file_id in exc_info.value.detail


@pytest.mark.asyncio
async def test_assert_rejects_non_image_content(
    db: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mrf, "storage", _FakeStorage(content_type="text/plain"))

    with pytest.raises(HTTPException) as exc_info:
        await mrf.assert_reference_image_file_id(db, file_id="img-1")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_assert_rejects_missing_file_row() -> None:
    empty = _FakeSession({})

    with pytest.raises(HTTPException) as exc_info:
        await mrf.assert_reference_image_file_id(empty, file_id="ghost")

    assert exc_info.value.status_code == 400
