"""优云智算 MiniMax H3 视频生成：`POST /minimax/v2/video_generation`。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput, _strip_optional_b64
from app.core.integrations.compshare.client import (
    DEFAULT_STATUS_TIMEOUT_S,
    DEFAULT_SUBMIT_TIMEOUT_S,
    PROVIDER_NAME,
    compshare_base_url,
    compshare_headers,
    ensure_business_success,
    extract_task_id,
    log_json_body,
    require_httpx,
    safe_text,
    task_payload,
)
from app.core.integrations.compshare.video_capabilities import (
    DEFAULT_COMPSHARE_VIDEO_DURATION_S,
    DEFAULT_COMPSHARE_VIDEO_RESOLUTION,
    validate_compshare_video_options,
    validate_h3_reference_material,
)
from app.core.integrations.http_logging import (
    log_media_http_request,
    log_media_http_response,
)
from app.core.integrations.openai.video_payload import to_image_data_url


class CompshareVideoApiAdapter:
    """MiniMax H3 视频 HTTP；异步任务，由 Task 层按 `poll_interval_s` 轮询。"""

    async def create_video_task(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float = DEFAULT_SUBMIT_TIMEOUT_S,
    ) -> str:
        httpx = require_httpx()
        validate_compshare_video_options(input_)

        model = (input_.model or "").strip()
        if not model:
            raise RuntimeError("优云智算视频生成需要模型名称（请在请求中指定模型）")

        body = build_compshare_video_body(input_)
        base_url = compshare_base_url(cfg)
        url = f"{base_url}/minimax/v2/video_generation"
        headers = compshare_headers(cfg.api_key, idempotent=True)

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
                resp_text=safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        payload = ensure_business_success(data, operation="视频提交")
        return extract_task_id(payload, operation="视频提交")

    async def get_video_task(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        timeout_s: float = DEFAULT_STATUS_TIMEOUT_S,
    ) -> dict[str, Any]:
        httpx = require_httpx()
        base_url = compshare_base_url(cfg)
        url = f"{base_url}/minimax/v2/query/video_generation/{quote(task_id, safe='')}"
        headers = compshare_headers(cfg.api_key)

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="query_video_task",
                method="GET",
                url=url,
                headers=headers,
                body_log=log_json_body({"task_id": task_id}),
            )
            r = await client.get(url, headers=headers)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="query_video_task",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        payload = ensure_business_success(data, operation="视频查询")
        return task_payload(payload)


def build_compshare_video_body(input_: VideoGenerationInput) -> dict[str, Any]:
    """按参考实现的 content[] 协议构造请求体。

    两种互斥的素材模式：
    - 首尾帧模式：用 role=first_frame/last_frame 提交（平台对图片支持 Data URL，上限 30 MiB）；
    - 参考图模式：每张图一个 role=reference_image，**顺序即提示词里 <Picture N> 的编号顺序**。

    参考视频/参考音频只接受公网 HTTP(S)，Jellyfish 暂不产生这两类素材。
    """
    validate_h3_reference_material(input_)

    content: list[dict[str, Any]] = []

    prompt = (input_.prompt or "").strip()
    if prompt:
        content.append({"type": "text", "text": prompt})

    references = [
        item.strip() for item in (input_.reference_images or []) if item and item.strip()
    ]
    if references:
        for item in references:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": to_image_data_url(item)},
                    "role": "reference_image",
                }
            )
    else:
        first = _strip_optional_b64(input_.first_frame_base64)
        last = _strip_optional_b64(input_.last_frame_base64)
        key = _strip_optional_b64(input_.key_frame_base64)
        # 只给关键帧时按首帧处理（平台省略 role 也是首帧）。
        if not first and not last and key:
            first = key

        if first:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": to_image_data_url(first)},
                    "role": "first_frame",
                }
            )
        if last:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": to_image_data_url(last)},
                    "role": "last_frame",
                }
            )

    body: dict[str, Any] = {
        "model": input_.model,
        "content": content,
        "resolution": DEFAULT_COMPSHARE_VIDEO_RESOLUTION,
        "duration": round(float(input_.seconds or DEFAULT_COMPSHARE_VIDEO_DURATION_S)),
    }
    if input_.ratio:
        body["ratio"] = input_.ratio
    if input_.watermark is not None:
        body["aigc_watermark"] = bool(input_.watermark)
    # A5：平台自带的提示词优化，默认关闭（提示词内容由 Jellyfish 自己控制）。
    if input_.use_context_ir:
        body["use_context_ir"] = True
        if input_.skill_id:
            body["skill_id"] = input_.skill_id
    return body


def video_url_from_task(task: dict[str, Any]) -> str:
    content = task.get("content")
    if isinstance(content, dict):
        url = content.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return ""
