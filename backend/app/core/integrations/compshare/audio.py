"""优云智算 IndexTTS 2.5 语音合成：`POST /audio/v1/speech/jobs`。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

from app.core.contracts.audio_generation import AudioGenerationInput
from app.core.contracts.provider import ProviderConfig
from app.core.integrations.compshare.audio_capabilities import (
    resolve_compshare_voice_source,
    validate_compshare_audio_options,
)
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
from app.core.integrations.http_logging import (
    log_media_http_request,
    log_media_http_response,
)

# 平台支持的语种写法归一化表（默认中文）。
_LANGUAGE_TABLE = {
    "zh": "ZH",
    "zh-cn": "ZH",
    "zh-tw": "ZH",
    "cn": "ZH",
    "中文": "ZH",
    "汉语": "ZH",
    "普通话": "ZH",
    "中英混合": "ZH",
    "en": "EN",
    "en-us": "EN",
    "en-gb": "EN",
    "英文": "EN",
    "英语": "EN",
    "ja": "JA",
    "jp": "JA",
    "日文": "JA",
    "日语": "JA",
    "es": "ES",
    "西班牙语": "ES",
    "ar": "AR",
    "阿拉伯语": "AR",
}
DEFAULT_AUDIO_LANGUAGE = "ZH"


class CompshareAudioApiAdapter:
    """IndexTTS 2.5 语音 HTTP；异步任务，由 Task 层按 `poll_interval_s` 轮询。"""

    async def create_speech_job(
        self,
        *,
        cfg: ProviderConfig,
        input_: AudioGenerationInput,
        timeout_s: float = DEFAULT_SUBMIT_TIMEOUT_S,
    ) -> str:
        httpx = require_httpx()
        validate_compshare_audio_options(input_)

        model = (input_.model or "").strip()
        if not model:
            raise RuntimeError("优云智算语音生成需要模型名称（请在请求中指定模型）")

        voice = (input_.voice or "").strip()
        if not voice:
            raise RuntimeError(
                "优云智算语音生成需要音色 ID（voice）；"
                "可用 GET /audio/v1/voices?kind=preset 查询预设音色"
            )

        body = build_compshare_speech_body(input_)
        base_url = compshare_base_url(cfg)
        url = f"{base_url}/audio/v1/speech/jobs"
        headers = compshare_headers(cfg.api_key, idempotent=True)

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="create_speech_job",
                method="POST",
                url=url,
                headers=headers,
                body_log=log_json_body(body),
            )
            r = await client.post(url, headers=headers, json=body)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="create_speech_job",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        payload = ensure_business_success(data, operation="语音提交")
        return extract_task_id(payload, operation="语音提交")

    async def get_speech_job(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        timeout_s: float = DEFAULT_STATUS_TIMEOUT_S,
    ) -> dict[str, Any]:
        httpx = require_httpx()
        base_url = compshare_base_url(cfg)
        url = f"{base_url}/audio/v1/speech/jobs/{quote(task_id, safe='')}"
        headers = compshare_headers(cfg.api_key)

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            log_media_http_request(
                provider=PROVIDER_NAME,
                operation="query_speech_job",
                method="GET",
                url=url,
                headers=headers,
                body_log=log_json_body({"task_id": task_id}),
            )
            r = await client.get(url, headers=headers)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_media_http_response(
                provider=PROVIDER_NAME,
                operation="query_speech_job",
                status_code=r.status_code,
                elapsed_ms=dt_ms,
                resp_text=safe_text(r),
            )
            r.raise_for_status()
            data = r.json()

        payload = ensure_business_success(data, operation="语音查询")
        return task_payload(payload)

    async def list_voices(
        self,
        *,
        cfg: ProviderConfig,
        kind: str = "preset",
        timeout_s: float = DEFAULT_STATUS_TIMEOUT_S,
    ) -> list[dict[str, Any]]:
        """音色列表：`kind=preset` 预设 / `kind=custom` 自定义。"""
        httpx = require_httpx()
        base_url = compshare_base_url(cfg)
        url = f"{base_url}/audio/v1/voices?kind={quote(kind, safe='')}"
        headers = compshare_headers(cfg.api_key)

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()

        payload = ensure_business_success(data, operation="音色列表")
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]


def build_compshare_speech_body(input_: AudioGenerationInput) -> dict[str, Any]:
    """按参考实现构造语音任务请求体（仅输出 WAV）。"""
    source = input_.voice_source or resolve_compshare_voice_source(input_.model)
    body: dict[str, Any] = {
        "text": (input_.text or "").strip(),
        "language": normalize_language(input_.language),
        "voice": {"source": source, "voice_id": (input_.voice or "").strip()},
    }
    if input_.speed is not None and input_.speed > 0:
        body["speed"] = float(input_.speed)
    emotion = (input_.emotion or "").strip()
    if emotion:
        body["emotion_description"] = emotion
    return body


def normalize_language(value: Any) -> str:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return DEFAULT_AUDIO_LANGUAGE
    return _LANGUAGE_TABLE.get(raw.lower(), raw.upper())


def audio_url_from_task(task: dict[str, Any]) -> str:
    url = task.get("output_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return ""
