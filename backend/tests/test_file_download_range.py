"""下载端点 HTTP Range 支持与下载文件名的回归测试。

守护的核心性质：
- `build_download_response` 恒回 `Accept-Ranges: bytes`；
- 带 `Range` 时回 206 + `Content-Range: bytes {start}-{end}/{total}`；
- `start` 越界时 416，且异常头上带 `Content-Range: bytes */total`；
- `http_exception_handler` 必须转发 `exc.headers`，否则 416 的语义头被丢弃；
- 下载文件名用 `files.name`，而不是存储对象的随机 key basename。
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi import HTTPException

from app.main import http_exception_handler
from app.services.studio import files as files_service

STORAGE_KEY = "exports/proj-e2e/937235bd-ddcd-4f84-8c05-8b21a189931b.mp4"


class _FakeStorage:
    """记录下载调用，并只按区间长度回字节。"""

    def __init__(self, *, size: int) -> None:
        self.size = size
        self.downloads: list[tuple[str, tuple[int, int] | None]] = []

    async def download_file(
        self, *, key: str, byte_range: tuple[int, int] | None = None
    ) -> bytes:
        self.downloads.append((key, byte_range))
        if byte_range is None:
            return b"x" * self.size
        start, end = byte_range
        return b"x" * (end - start + 1)

    async def get_file_info(self, *, key: str) -> SimpleNamespace:
        return SimpleNamespace(size=self.size)


def _patch(monkeypatch, *, size: int, name: str = "成片", thumbnail: str | None = None) -> _FakeStorage:
    """注入假的 FileItem 与 storage。

    ``thumbnail`` 需显式给出：服务层用它判断对象存储是否有公开域名，
    绝对 URL 会走 302 重定向而非流式代理，两个分支都要能被调到。
    """
    entry = SimpleNamespace(
        id="file-1", name=name, storage_key=STORAGE_KEY, thumbnail=thumbnail
    )
    fake = _FakeStorage(size=size)

    async def _fake_get_or_404(db, model, entity_id, **kwargs):
        return entry

    monkeypatch.setattr(files_service, "get_or_404", _fake_get_or_404)
    monkeypatch.setattr(files_service, "storage", fake)
    return fake


@pytest.mark.parametrize(
    ("header", "total", "expected"),
    [
        (None, 1000, None),
        ("", 1000, None),
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=500-", 1000, (500, 999)),
        ("bytes=-100", 1000, (900, 999)),
        # end 超出总量时收敛到最后一字节
        ("bytes=0-99999", 1000, (0, 999)),
        # 多段 Range 不支持，退化为整文件
        ("bytes=0-99,200-299", 1000, None),
        # 非 bytes 单位 / 非法语法
        ("items=0-99", 1000, None),
        ("bytes=abc-", 1000, None),
        ("bytes=-0", 1000, None),
        ("bytes=-", 1000, None),
    ],
)
def test_parse_byte_range(header: str | None, total: int, expected) -> None:
    assert files_service._parse_byte_range(header, total) == expected


def test_parse_byte_range_out_of_range_raises_416() -> None:
    with pytest.raises(HTTPException) as exc_info:
        files_service._parse_byte_range("bytes=1000-", 1000)
    assert exc_info.value.status_code == 416
    assert exc_info.value.headers == {"Content-Range": "bytes */1000"}


@pytest.mark.asyncio
async def test_full_download_advertises_accept_ranges(monkeypatch) -> None:
    fake = _patch(monkeypatch, size=1000)
    resp = await files_service.build_download_response(None, file_id="file-1")
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == "1000"
    assert "content-range" not in resp.headers
    # 无 Range 时不得多打一次 HEAD，也不得带 byte_range 下载
    assert fake.downloads == [(STORAGE_KEY, None)]


@pytest.mark.asyncio
async def test_ranged_download_returns_206(monkeypatch) -> None:
    fake = _patch(monkeypatch, size=1000)
    resp = await files_service.build_download_response(
        None, file_id="file-1", range_header="bytes=0-99"
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-99/1000"
    assert resp.headers["content-length"] == "100"
    assert fake.downloads == [(STORAGE_KEY, (0, 99))]


@pytest.mark.asyncio
async def test_suffix_range_returns_tail(monkeypatch) -> None:
    _patch(monkeypatch, size=1000)
    resp = await files_service.build_download_response(
        None, file_id="file-1", range_header="bytes=-100"
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 900-999/1000"


@pytest.mark.asyncio
async def test_multi_range_falls_back_to_full_content(monkeypatch) -> None:
    _patch(monkeypatch, size=1000)
    resp = await files_service.build_download_response(
        None, file_id="file-1", range_header="bytes=0-99,200-299"
    )
    assert resp.status_code == 200
    assert resp.headers["content-length"] == "1000"


@pytest.mark.asyncio
async def test_content_disposition_uses_business_name(monkeypatch) -> None:
    _patch(monkeypatch, size=10, name="全链路最小测试 deef6dc3-成片")
    resp = await files_service.build_download_response(None, file_id="file-1")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert unquote(disposition.split("UTF-8''", 1)[1]) == "全链路最小测试 deef6dc3-成片.mp4"


def test_download_filename_appends_suffix_only_once() -> None:
    entry = SimpleNamespace(name="成片.mp4", storage_key=STORAGE_KEY)
    assert files_service._build_download_filename(entry) == "成片.mp4"


def test_download_filename_falls_back_to_storage_basename() -> None:
    entry = SimpleNamespace(name="", storage_key=STORAGE_KEY)
    assert files_service._build_download_filename(entry) == "937235bd-ddcd-4f84-8c05-8b21a189931b.mp4"


@pytest.mark.asyncio
async def test_http_exception_handler_forwards_headers() -> None:
    exc = HTTPException(
        status_code=416,
        detail="Requested range not satisfiable",
        headers={"Content-Range": "bytes */1000"},
    )
    resp = await http_exception_handler(None, exc)  # type: ignore[arg-type]
    assert resp.status_code == 416
    assert resp.headers["content-range"] == "bytes */1000"
