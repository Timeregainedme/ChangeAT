from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

from fastapi import HTTPException, status

from app.models.llm import ModelCategoryKey


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    key: str
    display_name: str
    aliases: tuple[str, ...]
    supported_categories: tuple[ModelCategoryKey, ...]
    default_base_url: str | None = None
    requires_api_key: bool = True
    requires_api_secret: bool = False
    is_experimental: bool = False


_SPECS_BY_KEY: dict[str, ProviderSpec] = {}
_KEY_BY_ALIAS: dict[str, str] = {}
_LOCK = RLock()


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def register_provider(spec: ProviderSpec) -> None:
    key = _norm(spec.key)
    if not key:
        raise ValueError("provider key cannot be empty")
    if not spec.supported_categories:
        raise ValueError(f"provider {spec.key!r} must define supported_categories")

    aliases = tuple({a for a in (spec.aliases or ()) if _norm(a)})
    normalized_spec = ProviderSpec(
        key=key,
        display_name=(spec.display_name or spec.key).strip(),
        aliases=aliases,
        supported_categories=spec.supported_categories,
        default_base_url=(spec.default_base_url or "").strip() or None,
        requires_api_key=bool(spec.requires_api_key),
        requires_api_secret=bool(spec.requires_api_secret),
        is_experimental=bool(spec.is_experimental),
    )

    with _LOCK:
        existing = _SPECS_BY_KEY.get(key)
        if existing is not None and existing != normalized_spec:
            raise ValueError(f"provider key already registered with different spec: {key}")
        _SPECS_BY_KEY[key] = normalized_spec
        _KEY_BY_ALIAS[key] = key
        for alias in normalized_spec.aliases:
            alias_key = _norm(alias)
            if alias_key in _KEY_BY_ALIAS and _KEY_BY_ALIAS[alias_key] != key:
                raise ValueError(f"provider alias conflict: {alias!r}")
            _KEY_BY_ALIAS[alias_key] = key


def register_many(specs: list[ProviderSpec]) -> None:
    for spec in specs:
        register_provider(spec)


def list_registered_providers(category: ModelCategoryKey | None = None) -> list[ProviderSpec]:
    with _LOCK:
        values = list(_SPECS_BY_KEY.values())
    if category is None:
        return sorted(values, key=lambda x: x.key)
    return sorted((x for x in values if category in x.supported_categories), key=lambda x: x.key)


def get_provider_spec(provider_key: str) -> ProviderSpec:
    key = _norm(provider_key)
    with _LOCK:
        spec = _SPECS_BY_KEY.get(key)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unsupported provider key: {provider_key!r}",
        )
    return spec


def resolve_provider_key_from_name(name: str) -> str:
    alias = _norm(name)
    with _LOCK:
        key = _KEY_BY_ALIAS.get(alias)
    if key:
        return key
    # 兼容历史“包含式”命名（如 Doubao Video / bytedance-xxx）。
    if "volc" in alias or "doubao" in alias or "bytedance" in alias:
        return "volcengine"
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Unsupported provider name: {name!r}",
    )


def try_resolve_provider_key_from_name(name: str) -> str | None:
    """与 resolve_provider_key_from_name 同义，但无法识别时返回 None 而不是抛 503。

    适用于「能识别就按供应商定制，不能识别就走默认」的宽松路径。
    """
    try:
        return resolve_provider_key_from_name(name)
    except HTTPException:
        return None


# 各供应商的「思考模式」开关参数并不统一，不能一套参数打天下：
# - 阿里百炼 / DashScope 兼容端点用 enable_thinking: bool
# - DeepSeek 用 thinking: {"type": "enabled"|"disabled"}（思考默认开启，effort 默认 high）
# 未登记的供应商不下发任何思考开关，避免把对方不认识的字段塞进请求体。
def _dashscope_thinking_body(enabled: bool) -> dict[str, Any]:
    return {"enable_thinking": enabled}


def _deepseek_thinking_body(enabled: bool) -> dict[str, Any]:
    return {"thinking": {"type": "enabled" if enabled else "disabled"}}


_THINKING_BODY_BUILDERS: dict[str, Callable[[bool], dict[str, Any]]] = {
    "aliyun_bailian": _dashscope_thinking_body,
    "deepseek": _deepseek_thinking_body,
}


def thinking_extra_body(provider_key: str | None, *, enabled: bool) -> dict[str, Any]:
    """按供应商 key 生成思考模式开关的 extra_body 片段；未登记供应商返回空字典。"""
    builder = _THINKING_BODY_BUILDERS.get(_norm(provider_key or ""))
    return builder(enabled) if builder else {}


def extra_headers_for_provider(provider_name: str, base_url: str | None) -> dict[str, str]:
    """按供应商生成需要额外携带的请求头。

    目前只有 OpenCode Zen 需要：
    - 它的订阅通道 `/zen/go/v1` 要求 `x-opencode-session` 才能做请求路由，
      缺失时直接 400 `MissingSessionID`；
    - 同时要求 `x-opencode-client` 标识调用方。
    会话 ID 只用于网关路由，不需要与任何服务端状态对应，因此每次构建客户端时
    生成一个新的 UUID 即可（同一客户端内的多次请求复用同一个值）。
    """
    name = _norm(provider_name)
    url = (base_url or "").strip().lower()
    if "opencode" not in name and "opencode.ai" not in url:
        return {}
    return {
        "x-opencode-session": str(uuid.uuid4()),
        "x-opencode-client": "opencode",
    }


def thinking_extra_body_for_provider_name(provider_name: str, *, enabled: bool) -> dict[str, Any]:
    """按供应商显示名（providers.name）解析出 key 后再生成思考开关参数。"""
    return thinking_extra_body(try_resolve_provider_key_from_name(provider_name), enabled=enabled)


def is_provider_category_supported(provider_key: str, category: ModelCategoryKey) -> bool:
    spec = get_provider_spec(provider_key)
    return category in spec.supported_categories
