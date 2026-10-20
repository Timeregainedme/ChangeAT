from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.core.db_sync import _to_sync_database_url
from app.core.task_manager import SyncSqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus


def test_to_sync_database_url_converts_async_drivers() -> None:
    """同步 URL 只替换 driver，库名/文件名原样保留（不参与改名）。"""
    assert (
        _to_sync_database_url("mysql+aiomysql://root:123456@localhost:3306/dyeingtime")
        == "mysql+pymysql://root:123456@localhost:3306/dyeingtime"
    )
    assert _to_sync_database_url("sqlite+aiosqlite:///./dyeingtime.db") == "sqlite:///./dyeingtime.db"


def test_sync_task_store_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    import app.models.task  # noqa: F401

    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        row = GenerationTask(
            id="task-1",
            mode=GenerationDeliveryMode.async_polling,
            status=GenerationTaskStatus.pending,
            progress=0,
            payload={"hello": "world"},
            result=None,
            error="",
        )
        db.add(row)
        db.commit()

        store = SyncSqlAlchemyTaskStore(db)
        loaded = store.get("task-1")
        assert loaded is not None
        assert loaded.payload == {"hello": "world"}

        store.set_progress("task-1", 66)
        store.set_status("task-1", TaskStatus.running)
        store.set_result("task-1", {"ok": True})
        db.commit()

        refreshed = store.get("task-1")
        assert refreshed is not None
        assert refreshed.progress == 66
        assert refreshed.status == TaskStatus.running
        assert refreshed.result == {"ok": True}
