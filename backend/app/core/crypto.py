"""敏感字段的对称加密。

用途：供应商 `api_key` / `api_secret` 落库前加密，避免数据库备份、慢查询日志、
`SELECT *` 之类的常规运维动作把明文密钥带出去。

为什么选 Fernet（`cryptography`）：
- 自带 HMAC 完整性校验，密文被截断/篡改会直接抛错，而不是解出一段乱码再发给供应商；
- 提供 key 轮换能力（`MultiFernet`），后续换密钥不需要停机重写全表；
- `cryptography` 已是既有依赖（PyJWT 使用），不引入新依赖。

密钥来源（`app/config.py::settings`）：
1. 优先 `SECRETS_KEY`：URL-safe base64 编码的 32 字节，可用
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成；
2. 未配置时从 `JWT_SECRET` 派生，并打印一次告警。

第 2 条是为了让本地开发与测试无需额外配置，但它有明确代价：
**轮换 JWT_SECRET 会导致所有已加密的 API Key 无法解密**。
生产环境必须显式配置独立的 `SECRETS_KEY`。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

# Fernet 密文前缀。用于区分「已加密」与「历史明文」：
# 存量数据的 api_key 是明文，直接解密会失败；带前缀判断可以避免用异常做流程控制，
# 也便于迁移脚本快速筛出未加密的行。
CIPHERTEXT_PREFIX = "enc:v1:"

_warned_fallback = False


def _derive_key_from_jwt_secret() -> str:
    """从 JWT_SECRET 派生 Fernet key（仅用于开发/测试兜底）。"""
    digest = hashlib.sha256(f"{settings.jwt_secret}:provider-secrets".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


def _load_key() -> str:
    """解析当前生效的 Fernet key。"""
    global _warned_fallback

    configured = (getattr(settings, "secrets_key", "") or "").strip()
    if configured:
        return configured

    if not settings.jwt_secret:
        raise RuntimeError(
            "缺少加密密钥：请配置 SECRETS_KEY（推荐）或 JWT_SECRET 后再启动"
        )

    if not _warned_fallback:
        _warned_fallback = True
        logger.warning(
            "SECRETS_KEY 未配置，敏感字段加密回退为从 JWT_SECRET 派生密钥。"
            "轮换 JWT_SECRET 将导致既有 API Key 无法解密，生产环境请改用独立 SECRETS_KEY。"
        )
    return _derive_key_from_jwt_secret()


def _fernet() -> Fernet:
    return Fernet(_load_key())


def is_encrypted(value: str | None) -> bool:
    """判断值是否为本模块产出的密文。"""
    return bool(value) and str(value).startswith(CIPHERTEXT_PREFIX)


def encrypt_secret(value: str | None) -> str:
    """加密敏感字符串。

    - `None` / 空串原样返回：空 api_key 在业务上有「未配置」的含义，
      加密成密文会让「是否已配置」的判断失效；
    - 已是密文则不再重复加密（幂等），避免迁移脚本重复执行导致双重加密。
    """
    if not value:
        return value or ""
    if is_encrypted(value):
        return value
    token = _fernet().encrypt(str(value).encode()).decode()
    return f"{CIPHERTEXT_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    """解密敏感字符串。

    兼容策略：非密文（历史明文）原样返回，让服务在迁移脚本执行前也能正常工作。
    这是刻意的过渡设计——上线顺序是先发代码、再跑 `scripts/encrypt_provider_keys.py`，
    期间不允许因为「读到旧明文」而让供应商配置全部不可用。
    """
    if not value:
        return value or ""
    if not is_encrypted(value):
        return value

    token = str(value)[len(CIPHERTEXT_PREFIX):]
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # 密钥被换过（例如 JWT_SECRET 轮换）时会出现。
        # 不让整个接口 500：返回空串并记 error，让上层按「未配置密钥」处理，
        # 同时留下明确的可检索日志。
        logger.error(
            "敏感字段解密失败：密钥可能已轮换。请检查 SECRETS_KEY 是否与写入时一致，"
            "或重新录入该供应商的 API Key。"
        )
        return ""
