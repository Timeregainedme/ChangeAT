"""PIX 图片生成：`POST /api/v1/model-runtime/invoke` + 统一任务轮询。"""

from __future__ import annotations

import time
from typing import Any

from app.core.contracts.image_generation import (
    ImageGenerationInput,
    ImageGenerationResult,
    ImageItem,
)
from app.core.contracts.provider import ProviderConfig
from app.core.integrations.http_logging import (
    log_media_http_request,
    log_media_http_response,
)
from app.core.integrations.image_capabilities import resolve_image_size
from app.core.integrations.pix import DEFAULT_PIX_BASE_URL
from app.core.integrations.pix.client import (
    DEFAULT_PIX_IMAGE_TOTAL_TIMEOUT_S,
    DEFAULT_PIX_POLL_INTERVAL_S,
    DEFAULT_PIX_SUBMIT_TIMEOUT_S,
    PROVIDER_NAME,
    PixApiAdapterBase,
    decode_base64_payload,
    extract_task_id,
    log_json_body,
    pix_headers,
    require_httpx,
)
from app.core.integrations.pix.image_capabilities import validate_pix_image_options

# 与 pix.ts 默认值一致：比例 1:1。
# 分辨率档位按项目既定规格统一为 `1K`（原为 2K）：角色卡/场景/道具等 purpose="generic"
# 的调用不传 size，落到这里就是最终档位；分镜参考帧走
# purpose="video_reference" + resolution_profile，仍按入参推导（standard→1K）。
DEFAULT_PIX_IMAGE_RATIO = "1:1"
DEFAULT_PIX_IMAGE_RESOLUTION = "1K"


class PixImageApiAdapter(PixApiAdapterBase):
    """PIX 图片生成 HTTP；无状态，可单测替换。"""

    async def create_image_task(
        self,
        *,
        cfg: ProviderConfig,
        inp: ImageGenerationInput,
        timeout_s: float = DEFAULT_PIX_SUBMIT_TIMEOUT_S,
    ) -> str:
        httpx = require_httpx()
        base_url = (cfg.base_url or DEFAULT_PIX_BASE_URL).rstrip("/")

        resolved_size = resolve_image_size(
            provider=PROVIDER_NAME,
            model=inp.model,
            purpose=inp.purpose,
            target_ratio=inp.target_ratio,
            resolution_profile=inp.resolution_profile,
            requested_size=inp.size,
        )
        resolved_input = inp.model_copy(update={"size": resolved_size})
        validate_pix_image_options(resolved_input)

        model_id = (resolved_input.model or "").strip()
        if not model_id:
            raise RuntimeError("PIX 图片生成需要 model_id（请在请求中指定模型名称）")

        reference_urls = await self._collect_reference_urls(
            cfg=cfg,
            inp=resolved_input,
            timeout_s=timeout_s,
        )
        body = build_pix_image_body(resolved_input, image_urls=reference_urls)
        headers = pix_headers(cfg.api_key)
        url = f"{base_url}/api/v1/model-runtime/invoke"

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="create_image_task",
                method="POST",
                url=url,
                headers=headers,
                body_log=log_json_body(body),
            )
            r = await client.post(url, headers=headers, json=body)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="create_image_task",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=_safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        if not isinstance(data, dict):
            raise RuntimeError(f"PIX 图片生成返回非法结构：{data!r}")
        return extract_task_id(data, operation="图片生成")

    async def generate(
        self,
        *,
        cfg: ProviderConfig,
        inp: ImageGenerationInput,
        timeout_s: float = DEFAULT_PIX_SUBMIT_TIMEOUT_S,
        poll_interval_s: float = DEFAULT_PIX_POLL_INTERVAL_S,
        total_timeout_s: float = DEFAULT_PIX_IMAGE_TOTAL_TIMEOUT_S,
    ) -> ImageGenerationResult:
        """提交任务并轮询到终态，返回统一的图片结果。"""
        task_id = await self.create_image_task(cfg=cfg, inp=inp, timeout_s=timeout_s)
        data = await self.wait_task(
            cfg=cfg,
            task_id=task_id,
            poll_interval_s=poll_interval_s,
            timeout_s=total_timeout_s,
        )
        output_url = str(data.get("output_url") or "").strip()
        return ImageGenerationResult(
            images=[ImageItem(url=output_url)],
            provider=PROVIDER_NAME,
            provider_task_id=task_id,
            status=str(data.get("status") or "succeeded"),
        )

    async def _collect_reference_urls(
        self,
        *,
        cfg: ProviderConfig,
        inp: ImageGenerationInput,
        timeout_s: float,
    ) -> list[str]:
        """把参考图转成 PIX 可接受的公网 URL（`data:` 负载先上传换取 URL）。

        PIX 的 `model-runtime/invoke` 只接受稳定的 http(s) 参考图 URL：直接把
        `data:image/png;base64,...` 塞进 `params.images` 会被 400 拒绝
        （`invalid_reference_provenance: reference image at images[0] is not a
        stable http(s) URL`）。平台侧 `resolve_reference_image_refs_by_file_ids`
        产出的正是 `data:` URL，所以这里必须先经 `upload_reference_file` 换链。
        """
        urls: list[str] = []
        for index, ref in enumerate(inp.images or []):
            candidate = (ref.image_url or ref.file_id or "").strip()
            if not candidate:
                continue
            if candidate.startswith(("http://", "https://")):
                urls.append(candidate)
                continue
            if not candidate.startswith("data:") and "base64" not in candidate:
                raise RuntimeError(
                    "PIX 图片参考素材需要 http(s) URL 或 data URL；"
                    f"images[{index}] 既不是两者之一（收到 file_id={ref.file_id!r}）。"
                    "请在上游把 file_id 解析为下载内容或 data URL。"
                )
            content, mime = decode_base64_payload(candidate)
            ext = "png" if "png" in mime else "jpg"
            urls.append(
                await self.upload_reference_file(
                    cfg=cfg,
                    content=content,
                    filename=f"reference{index}.{ext}",
                    content_type=mime,
                    timeout_s=timeout_s,
                )
            )
        return urls


def build_pix_image_body(
    inp: ImageGenerationInput,
    *,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """按 pix.ts 的 invoke 协议构造请求体。

    `image_urls` 必须是 PIX 可接受的稳定 http(s) URL；调用方负责把平台侧产出的
    `data:` 参考图先经 `upload_reference_file` 换成公网 URL（见 `_collect_reference_urls`）。
    """
    params: dict[str, Any] = {
        "prompt": inp.prompt or "",
        "aspect_ratio": inp.target_ratio or DEFAULT_PIX_IMAGE_RATIO,
        "resolution": inp.size or DEFAULT_PIX_IMAGE_RESOLUTION,
    }

    resolved_urls = [url for url in (image_urls or []) if url]
    if resolved_urls:
        params["images"] = resolved_urls
        params["mode"] = "multi-reference" if len(resolved_urls) > 1 else "image-edit"

    return {
        "model_id": inp.model,
        "modality": "image",
        "params": params,
    }


def _safe_text(r: Any) -> str:
    try:
        return r.text or ""
    except Exception:  # noqa: BLE001
        return ""
