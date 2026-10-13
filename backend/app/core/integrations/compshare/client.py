"""优云智算「模型 API」HTTP 基础设施：鉴权头、业务错误判定、任务字段提取。"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.contracts.provider import ProviderConfig
from app.core.integrations.compshare import DEFAULT_COMPSHARE_BASE_URL
from app.core.integrations.http_logging import json_dumps_for_log, safe_body_for_log_generic

PROVIDER_NAME = "compshare_model_api"

# 与参考实现一致：提交 120s、查询 60s；视频轮询 3s/总 30min，语音轮询 3s/总 20min。
DEFAULT_SUBMIT_TIMEOUT_S = 120.0
DEFAULT_STATUS_TIMEOUT_S = 60.0
DEFAULT_VIDEO_POLL_INTERVAL_S = 3.0
DEFAULT_AUDIO_POLL_INTERVAL_S = 3.0
DEFAULT_VIDEO_TOTAL_TIMEOUT_S = 1800.0
DEFAULT_AUDIO_TOTAL_TIMEOUT_S = 1200.0

# 素材体积上限（MiB），用于 Data URL 兜底前的体积校验。
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024


def require_httpx() -> Any:
    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("httpx is required for compshare generation tasks") from e
    return httpx


def compshare_base_url(cfg: ProviderConfig) -> str:
    return (cfg.base_url or DEFAULT_COMPSHARE_BASE_URL).rstrip("/")


def compshare_headers(api_key: str, *, idempotent: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if idempotent:
        headers["Idempotency-Key"] = uuid.uuid4().hex
    return headers


def ensure_business_success(data: Any, *, operation: str) -> dict[str, Any]:
    """HTTP 200 但 `RetCode` 非 0 视为业务失败。"""
    if not isinstance(data, dict):
        raise RuntimeError(f"优云智算 {operation} 返回非法结构：{data!r}")
    ret_code = data.get("RetCode")
    if isinstance(ret_code, bool):
        ret_code = None
    failed = False
    if isinstance(ret_code, (int, float)):
        failed = ret_code != 0
    elif isinstance(ret_code, str):
        failed = ret_code.strip() not in ("", "0")
    if failed:
        message = data.get("Message") or data.get("message") or ""
        raise RuntimeError(f"优云智算 {operation} 业务错误 RetCode={ret_code}：{message or data!r}")
    return data


def extract_task_id(data: dict[str, Any], *, operation: str) -> str:
    task_id = data.get("task_id")
    if isinstance(task_id, str) and task_id.strip():
        return task_id.strip()
    raise RuntimeError(f"优云智算 {operation} 未返回任务编号：{data!r}")


def task_payload(data: dict[str, Any]) -> dict[str, Any]:
    task = data.get("task")
    if isinstance(task, dict):
        return task
    return {}


def task_error_message(task: dict[str, Any]) -> str:
    error = task.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    direct = task.get("error_message")
    if isinstance(direct, str) and direct:
        return direct
    return "接口未说明原因"


def log_json_body(body: dict[str, Any]) -> str:
    return json_dumps_for_log(safe_body_for_log_generic(body))


def safe_text(r: Any) -> str:
    try:
        return r.text or ""
    except Exception:  # noqa: BLE001
        return ""


__all__ = [
    "PROVIDER_NAME",
    "DEFAULT_SUBMIT_TIMEOUT_S",
    "DEFAULT_STATUS_TIMEOUT_S",
    "DEFAULT_VIDEO_POLL_INTERVAL_S",
    "DEFAULT_AUDIO_POLL_INTERVAL_S",
    "DEFAULT_VIDEO_TOTAL_TIMEOUT_S",
    "DEFAULT_AUDIO_TOTAL_TIMEOUT_S",
    "MAX_IMAGE_BYTES",
    "MAX_VIDEO_BYTES",
    "MAX_AUDIO_BYTES",
    "compshare_base_url",
    "compshare_headers",
    "ensure_business_success",
    "extract_task_id",
    "log_json_body",
    "require_httpx",
    "safe_text",
    "task_error_message",
    "task_payload",
]
