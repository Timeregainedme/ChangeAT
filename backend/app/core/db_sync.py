"""SQLAlchemy 同步引擎与会话。

给 Celery worker 使用，避免在同步 worker 进程里承载 async DB runtime。
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.db import Base


def _to_sync_database_url(url: str) -> str:
    if url.startswith("mysql+aiomysql://"):
        return "mysql+pymysql://" + url.removeprefix("mysql+aiomysql://")
    if url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + url.removeprefix("sqlite+aiosqlite:///")
    return url


def _pin_mysql_session_utc(engine: Engine) -> None:
    """把 MySQL 连接的会话时区固定为 UTC。

    为什么需要：MySQL 的 DATETIME 不保存时区，驱动（pymysql）按**会话时区**把
    带 tzinfo 的 datetime 转成墙钟字符串。应用写入的 `published_at` 是
    `datetime.now(UTC)`，若会话时区仍是 `SYSTEM`（容器里常为 `Asia/Shanghai`），
    写出的墙钟就会被按 +08:00 解释，与同表 created_at/updated_at
    （服务端 NOW()，按会话时区）口径不一致（评审 D-5）。
    连接建立时显式 `SET time_zone = '+00:00'` 后，会话时区与 UTC 写入值一致，
    DATETIME 列的墙钟即等于 UTC 时刻。

    非 MySQL 方言（sqlite 等）没有会话时区语义，直接跳过。
    """
    if engine.dialect.name != "mysql":
        return

    @event.listens_for(engine, "connect")
    def _set_session_timezone(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")


def _build_sync_engine() -> Engine:
    engine = create_engine(
        _to_sync_database_url(settings.database_url),
        echo=settings.debug,
        future=True,
        pool_pre_ping=True,
    )
    _pin_mysql_session_utc(engine)
    return engine


engine_sync = _build_sync_engine()
sync_session_maker = sessionmaker(
    bind=engine_sync,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

__all__ = [
    "Base",
    "engine_sync",
    "sync_session_maker",
]
