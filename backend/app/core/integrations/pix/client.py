"""PIX 平台的 HTTP 客户端基础设施：统一轮询、参考素材上传、base64 解码。

协议对齐 `/Applications/data/providers/pix.ts`：
- 任务提交后返回 `task_id`；
- 统一通过 `GET /v1/tasks/{taskId}` 轮询，`is_final === true` 时读 `output_url`；
- 参考素材可上传 `POST /v1/files`（multipart 字段名 `file`）换取公网 URL。
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, BinaryIO

from app.core.contracts.provider import ProviderConfig
from app.core.integrations.http_logging import (
    json_dumps_for_log,
    log_media_http_request,
    log_media_http_response,
    safe_body_for_log_generic,
)
from app.core.integrations.pix import DEFAULT_PIX_BASE_URL

# 与 pix.ts 一致：每 6 秒查询一次任务状态。
DEFAULT_PIX_POLL_INTERVAL_S = 6.0
DEFAULT_PIX_SUBMIT_TIMEOUT_S = 120.0
DEFAULT_PIX_STATUS_TIMEOUT_S = 60.0
# pix.ts 中图片任务超时上限 10 分钟、视频任务 30 分钟。
DEFAULT_PIX_IMAGE_TOTAL_TIMEOUT_S = 600.0
DEFAULT_PIX_VIDEO_TOTAL_TIMEOUT_S = 1800.0

PROVIDER_NAME = "pix"


def require_httpx() -> Any:
    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("httpx is required for PIX generation tasks") from e
    return httpx


def pix_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def decode_base64_payload(value: str) -> tuple[bytes, str]:
    """把纯 base64 或 `data:<mime>;base64,...` 解码为 (bytes, mime)。"""
    raw = (value or "").strip()
    mime = "image/png"
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if ";" in header:
            mime = header[5:].split(";")[0].strip() or mime
        raw = payload
    if not raw:
        raise ValueError("PIX 参考素材为空，无法上传")
    return base64.b64decode(raw), mime


def extract_task_id(data: dict[str, Any], *, operation: str) -> str:
    """PIX 的 task_id 可能在顶层，也可能在 `data` 内（视频接口）。"""
    nested = data.get("data")
    candidates = [
        data.get("task_id"),
        nested.get("task_id") if isinstance(nested, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError(f"PIX {operation} 未返回任务 ID：{data!r}")


def is_final(data: dict[str, Any]) -> bool:
    value = data.get("is_final")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


class PixApiAdapterBase:
    """PIX 适配器公共能力：状态查询、轮询、参考素材上传。"""

    async def get_task(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        timeout_s: float = DEFAULT_PIX_STATUS_TIMEOUT_S,
    ) -> dict[str, Any]:
        httpx = require_httpx()
        base_url = (cfg.base_url or DEFAULT_PIX_BASE_URL).rstrip("/")
        headers = pix_headers(cfg.api_key)
        url = f"{base_url}/v1/tasks/{task_id}"

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="query_task",
                method="GET",
                url=url,
                headers=headers,
                body_log=json_dumps_for_log({"task_id": task_id}),
            )
            r = await client.get(url, headers=headers)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="query_task",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=_safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        if not isinstance(data, dict):
            raise RuntimeError(f"PIX 任务查询返回非法结构：{data!r}")
        return data

    async def wait_task(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        poll_interval_s: float = DEFAULT_PIX_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_PIX_VIDEO_TOTAL_TIMEOUT_S,
    ) -> dict[str, Any]:
        """轮询至 `is_final` 为真，返回含 `output_url` 的终态负载。"""
        deadline = time.monotonic() + timeout_s
        while True:
            data = await self.get_task(cfg=cfg, task_id=task_id)
            status = str(data.get("status") or "")
            if status == "failed":
                raise RuntimeError(f"PIX 任务失败：{data.get('error') or data.get('message') or data!r}")
            if is_final(data):
                output_url = str(data.get("output_url") or "").strip()
                if not output_url:
                    raise RuntimeError(f"PIX 任务已完成但未返回 output_url：{data!r}")
                return data
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"PIX 任务超时：task_id={task_id!r} timeout_s={timeout_s} last_status={status!r}"
                )
            await asyncio.sleep(poll_interval_s)

    async def upload_reference_file(
        self,
        *,
        cfg: ProviderConfig,
        content: bytes,
        filename: str = "upload.png",
        content_type: str = "image/png",
        timeout_s: float = DEFAULT_PIX_SUBMIT_TIMEOUT_S,
    ) -> str:
        """上传本地素材换取公网 URL（PIX 的 images/videos/audios 只接受 URL）。"""
        httpx = require_httpx()
        base_url = (cfg.base_url or DEFAULT_PIX_BASE_URL).rstrip("/")
        url = f"{base_url}/v1/files"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="upload_file",
                method="POST",
                url=url,
                headers=headers,
                body_log=json_dumps_for_log(
                    {"filename": filename, "content_type": content_type, "size_bytes": len(content)}
                ),
            )
            r = await client.post(url, headers=headers, files={"file": (filename, content, content_type)})
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="upload_file",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=_safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        file_url = ""
        if isinstance(data, dict):
            nested = data.get("data")
            for candidate in (
                data.get("url"),
                nested.get("url") if isinstance(nested, dict) else None,
            ):
                if isinstance(candidate, str) and candidate.strip():
                    file_url = candidate.strip()
                    break
        if not file_url:
            raise RuntimeError(f"PIX 素材上传未返回 URL：{data!r}")
        return file_url


def _safe_text(r: Any) -> str:
    try:
        return r.text or ""
    except Exception:  # noqa: BLE001
        return ""


def log_json_body(body: dict[str, Any]) -> str:
    return json_dumps_for_log(safe_body_for_log_generic(body))


__all__ = [
    "PROVIDER_NAME",
    "DEFAULT_PIX_POLL_INTERVAL_S",
    "DEFAULT_PIX_SUBMIT_TIMEOUT_S",
    "DEFAULT_PIX_STATUS_TIMEOUT_S",
    "DEFAULT_PIX_IMAGE_TOTAL_TIMEOUT_S",
    "DEFAULT_PIX_VIDEO_TOTAL_TIMEOUT_S",
    "PixApiAdapterBase",
    "decode_base64_payload",
    "extract_task_id",
    "is_final",
    "log_json_body",
    "pix_headers",
    "require_httpx",
]
