"""敏感字段加密回归测试。

守护的核心性质：
1. `provider.api_key` / `api_secret` 落库后**不是明文**；
2. ORM 读回来仍是明文（业务代码无需改动）；
3. 历史明文数据仍可读（上线过渡期不允许因为没跑迁移脚本而让供应商配置失效）；
4. 空值不被加密（否则「是否已配置」的判断会失效）；
5. 重复加密幂等（迁移脚本可重复执行）。

为什么必须查原始 SQL：
只断言 ORM 层的值没有意义 —— TypeDecorator 会在读取时解密，
即使库里是明文也能读对。只有绕过 ORM 直接查列，才能证明「落库即密文」。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.crypto import CIPHERTEXT_PREFIX, decrypt_secret, encrypt_secret, is_encrypted
from app.core.db import Base
from app.models.llm import Provider


async def _build_session() -> tuple[AsyncSession, object]:
    """建一个最小内存库（只依赖 providers 所需的表）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return maker, engine


def _provider(**overrides) -> Provider:
    data = {
        "id": "prov-1",
        "name": "测试供应商",
        "base_url": "https://example.com/v1",
        "api_key": "sk-plain-secret-123",
        "api_secret": "sec-plain-456",
        "description": "",
        "created_by": "",
    }
    data.update(overrides)
    return Provider(**data)


@pytest.mark.asyncio
async def test_api_key_is_encrypted_at_rest() -> None:
    """落库后列值必须是密文，且带版本前缀。"""
    maker, engine = await _build_session()
    try:
        async with maker() as session:
            session.add(_provider())
            await session.commit()

            raw = (
                await session.execute(
                    text("SELECT api_key, api_secret FROM providers WHERE id='prov-1'")
                )
            ).one()
            stored_key, stored_secret = raw

            assert stored_key != "sk-plain-secret-123"
            assert stored_secret != "sec-plain-456"
            assert stored_key.startswith(CIPHERTEXT_PREFIX)
            assert stored_secret.startswith(CIPHERTEXT_PREFIX)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_orm_roundtrip_returns_plaintext() -> None:
    """ORM 读取必须还原明文，否则所有供应商适配器都会拿密文去请求。"""
    maker, engine = await _build_session()
    try:
        async with maker() as session:
            session.add(_provider())
            await session.commit()
            session.expunge_all()

            loaded = await session.get(Provider, "prov-1")
            assert loaded is not None
            assert loaded.api_key == "sk-plain-secret-123"
            assert loaded.api_secret == "sec-plain-456"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_plaintext_row_is_readable() -> None:
    """历史明文行（未跑迁移脚本）必须仍可读。

    上线顺序是「先发代码，再跑迁移脚本」，期间旧数据是明文；
    若读取直接解密失败，供应商配置会在窗口期内全部不可用。
    """
    maker, engine = await _build_session()
    try:
        async with maker() as session:
            await session.execute(
                text(
                    "INSERT INTO providers (id, name, base_url, api_key, api_secret, description, "
                    "status, created_by, created_at, updated_at) "
                    "VALUES ('legacy-1', '旧供应商', 'https://legacy.example.com', "
                    "'sk-legacy-plain', '', '', 'testing', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await session.commit()
            session.expunge_all()

            loaded = await session.get(Provider, "legacy-1")
            assert loaded is not None
            assert loaded.api_key == "sk-legacy-plain"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_value_stays_empty() -> None:
    """空 api_key 表示「未配置」，不能被加密成一段密文。"""
    maker, engine = await _build_session()
    try:
        async with maker() as session:
            session.add(_provider(id="prov-empty", api_key="", api_secret=""))
            await session.commit()

            raw = (
                await session.execute(
                    text("SELECT api_key FROM providers WHERE id='prov-empty'")
                )
            ).scalar_one()
            assert raw == ""

            session.expunge_all()
            loaded = await session.get(Provider, "prov-empty")
            assert loaded is not None
            assert loaded.api_key == ""
    finally:
        await engine.dispose()


def test_encrypt_is_idempotent() -> None:
    """迁移脚本会在存量数据上重复执行，重复加密必须无副作用。"""
    once = encrypt_secret("sk-idempotent")
    twice = encrypt_secret(once)
    assert once == twice
    assert decrypt_secret(twice) == "sk-idempotent"


def test_plaintext_passthrough() -> None:
    """非密文输入（历史明文）解密时原样返回。"""
    assert is_encrypted("sk-plain") is False
    assert decrypt_secret("sk-plain") == "sk-plain"
    assert encrypt_secret("") == ""
