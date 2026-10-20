"""generated_video 接口响应壳测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.routes.film import generated_video as route
from app.dependencies import get_db
from app.main import app


class _FakeTaskRecord:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeTaskManager:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def create(self, *_args, **_kwargs) -> _FakeTaskRecord:
        return _FakeTaskRecord("video-task-1")


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def scalar(self, _stmt):  # noqa: ANN001
        """工作区归属解析一律放行。

        任务创建前会经 `resolve_workspace_id` 反查项目工作区，本替身没有业务数据，
        返回占位对象让流程继续；隔离语义由 `test_workspace_multitenancy.py` 覆盖。
        """
        return "ws-test"


async def _async_noop(*_args, **_kwargs) -> None:
    return None


def _override_db(db: _FakeDB):
    async def _get_db() -> AsyncGenerator[_FakeDB, None]:
        yield db

    return _get_db


def test_preview_video_generation_prompt_returns_success_envelope(client: TestClient, monkeypatch) -> None:
    db = _FakeDB()

    async def _fake_preview(*_args, **_kwargs):
        return "视频预览提示词", ["file-1", "file-2"], {
            "shot_id": "shot-1",
            "title": "镜头一",
            "script_excerpt": "主角转身看向门口。",
            "action_beats": ["主角转身", "视线停在门口"],
            "action_beat_phases": [
                {"text": "主角转身", "phase": "trigger"},
                {"text": "视线停在门口", "phase": "aftermath"},
            ],
            "previous_shot_summary": "标题：镜头零；剧本摘录：主角推门进入走廊",
            "next_shot_goal": "标题：镜头二；主角停住动作，保持警惕",
            "continuity_guidance": "承接上一镜头动作，不要像全新场面重新开局",
            "composition_anchor": "以走廊门口作为空间锚点",
            "screen_direction_guidance": "保持主角朝向和视线落点连续",
            "dialogue_summary": "",
            "characters": [],
            "scene": None,
            "props": [],
            "costumes": [],
            "camera": {"camera_shot": "MS", "angle": "EYE_LEVEL", "movement": "STATIC", "duration": 4},
            "atmosphere": "紧张",
            "visual_style": "现实",
            "style": "真人都市",
            "negative_prompt": "",
        }

    monkeypatch.setattr(route, "preview_prompt_and_images", _fake_preview)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/film/tasks/video/preview-prompt",
            json={
                "shot_id": "shot-1",
                "reference_mode": "first_last",
                "prompt": "生成一个压迫感强的镜头",
                "images": [],
                "ratio": "9:16",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "success"
    assert body["data"]["prompt"] == "视频预览提示词"
    assert body["data"]["images"] == ["file-1", "file-2"]
    assert body["data"]["pack"]["previous_shot_summary"].startswith("标题：镜头零")
    assert body["data"]["pack"]["next_shot_goal"].startswith("标题：镜头二")


def test_preview_video_generation_prompt_not_found_returns_api_response(
    client: TestClient, monkeypatch
) -> None:
    db = _FakeDB()

    async def _fake_preview(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Shot not found")

    monkeypatch.setattr(route, "preview_prompt_and_images", _fake_preview)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/film/tasks/video/preview-prompt",
            json={
                "shot_id": "shot-missing",
                "reference_mode": "text_only",
                "prompt": "仅文本生成",
                "images": [],
                "ratio": "16:9",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "Shot not found", "data": None, "meta": None}


async def _fake_readiness_ready(*_args, **_kwargs):
    return SimpleNamespace(ready=True, shot_id="shot-1", reference_mode="first", checks=[])


def test_create_video_generation_task_returns_created_envelope(client: TestClient, monkeypatch) -> None:
    db = _FakeDB()

    async def _fake_build_run_args(*_args, **_kwargs):
        return {"prompt": "最终视频提示词", "images": ["file-1"]}

    monkeypatch.setattr(route, "get_shot_video_readiness", _fake_readiness_ready)
    monkeypatch.setattr(route, "build_run_args", _fake_build_run_args)
    monkeypatch.setattr(route, "TaskManager", _FakeTaskManager)
    monkeypatch.setattr(route, "enqueue_task_execution", lambda task_id: SimpleNamespace(id=f"celery-{task_id}"))
    monkeypatch.setattr(route, "mark_shot_generating", _async_noop)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/film/tasks/video",
            json={
                "shot_id": "shot-1",
                "reference_mode": "first",
                "prompt": "生成一个节奏紧张的视频片段",
                "images": [],
                "ratio": "9:16",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["message"] == "success"
    assert body["data"]["task_id"] == "video-task-1"
    assert body["meta"] is None
    assert db.committed is True
    assert len(db.added) == 1


def test_create_video_generation_task_not_ready_returns_409(client: TestClient, monkeypatch) -> None:
    """评审 R-14：分镜未就绪时必须在建任务前拦截，而不是先 201 再在任务里失败。"""
    db = _FakeDB()

    async def _fake_readiness_not_ready(*_args, **_kwargs):
        return SimpleNamespace(
            ready=False,
            shot_id="shot-1",
            reference_mode="first",
            checks=[
                SimpleNamespace(key="reference_frames_ready", ok=False, message="缺少参考帧：first"),
                SimpleNamespace(key="video_model_ready", ok=True, message="ok"),
            ],
        )

    async def _fail_build_run_args(*_args, **_kwargs):
        raise AssertionError("readiness 未通过时不应进入 build_run_args")

    monkeypatch.setattr(route, "get_shot_video_readiness", _fake_readiness_not_ready)
    monkeypatch.setattr(route, "build_run_args", _fail_build_run_args)
    monkeypatch.setattr(route, "TaskManager", _FakeTaskManager)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/film/tasks/video",
            json={
                "shot_id": "shot-1",
                "reference_mode": "first",
                "prompt": "生成一个节奏紧张的视频片段",
                "images": [],
                "ratio": "9:16",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == 409
    assert "not ready" in body["message"]
    assert "缺少参考帧" in body["message"]
    assert db.committed is False
    assert db.added == []


def test_create_video_generation_task_validation_error_returns_api_response(client: TestClient) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/film/tasks/video",
            json={
                "shot_id": "shot-1",
                "reference_mode": "invalid-mode",
                "prompt": "bad",
                "images": [],
                "ratio": "16:9",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert body["data"] is None
    assert "reference_mode" in body["message"]
