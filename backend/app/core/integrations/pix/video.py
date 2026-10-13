"""PIX 视频生成：`POST /v1/media/generate` + 统一任务轮询。"""

from __future__ import annotations

import time
from typing import Any

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput, _strip_optional_b64
from app.core.integrations.http_logging import (
    log_media_http_request,
    log_media_http_response,
)
from app.core.integrations.pix import DEFAULT_PIX_BASE_URL
from app.core.integrations.pix.client import (
    DEFAULT_PIX_SUBMIT_TIMEOUT_S,
    PROVIDER_NAME,
    PixApiAdapterBase,
    decode_base64_payload,
    extract_task_id,
    log_json_body,
    pix_headers,
    require_httpx,
)
from app.core.integrations.pix.video_capabilities import (
    PIX_VIDEO_DEFAULT_RESOLUTION,
    validate_pix_video_options,
)

DEFAULT_PIX_VIDEO_DURATION_S = 5
DEFAULT_PIX_VIDEO_RATIO = "16:9"


class PixVideoApiAdapter(PixApiAdapterBase):
    """PIX 视频生成 HTTP；异步任务，由 Task 层按 `poll_interval_s` 轮询。"""

    async def create_media_task(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float = DEFAULT_PIX_SUBMIT_TIMEOUT_S,
    ) -> str:
        httpx = require_httpx()
        base_url = (cfg.base_url or DEFAULT_PIX_BASE_URL).rstrip("/")

        validate_pix_video_options(input_)

        model = (input_.model or "").strip()
        if not model:
            raise RuntimeError("PIX 视频生成需要模型名称（请在请求中指定模型）")

        image_urls = await self._collect_frame_urls(cfg=cfg, input_=input_, timeout_s=timeout_s)
        body = build_pix_video_body(input_, image_urls=image_urls)

        headers = pix_headers(cfg.api_key)
        url = f"{base_url}/v1/media/generate"

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="create_video_task",
                method="POST",
                url=url,
                headers=headers,
                body_log=log_json_body(body),
            )
            r = await client.post(url, headers=headers, json=body)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="create_video_task",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=_safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        if not isinstance(data, dict):
            raise RuntimeError(f"PIX 视频生成返回非法结构：{data!r}")
        return extract_task_id(data, operation="视频生成")

    async def _collect_frame_urls(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float,
    ) -> list[str]:
        """把首帧/关键帧/尾帧转成 PIX 可接受的公网 URL（必要时先上传）。"""
        first = _strip_optional_b64(input_.first_frame_base64) or _strip_optional_b64(
            input_.key_frame_base64
        )
        last = _strip_optional_b64(input_.last_frame_base64)

        urls: list[str] = []
        for index, frame in enumerate([f for f in (first, last) if f]):
            if frame.startswith(("http://", "https://")):
                urls.append(frame)
                continue
            content, mime = decode_base64_payload(frame)
            ext = "png" if "png" in mime else "jpg"
            urls.append(
                await self.upload_reference_file(
                    cfg=cfg,
                    content=content,
                    filename=f"frame{index}.{ext}",
                    content_type=mime,
                    timeout_s=timeout_s,
                )
            )
        return urls


def build_pix_video_body(input_: VideoGenerationInput, *, image_urls: list[str]) -> dict[str, Any]:
    """按 pix.ts 的 media/generate 协议构造请求体。

    mode 推导：两帧（首+尾）→ `first-last`；单帧 → `first-frame`；纯文本 → `text-to-video`。
    """
    if len(image_urls) > 1:
        mode = "first-last"
    elif image_urls:
        mode = "first-frame"
    else:
        mode = "text-to-video"

    params: dict[str, Any] = {
        "mode": mode,
        "duration": str(int(input_.seconds or DEFAULT_PIX_VIDEO_DURATION_S)),
        "resolution": str(PIX_VIDEO_DEFAULT_RESOLUTION).lower(),
        "aspect_ratio": input_.ratio or DEFAULT_PIX_VIDEO_RATIO,
    }
    if image_urls:
        params["images"] = image_urls

    return {
        "model": input_.model,
        "prompt": input_.prompt or "",
        "params": params,
    }


def _safe_text(r: Any) -> str:
    try:
        return r.text or ""
    except Exception:  # noqa: BLE001
        return ""
