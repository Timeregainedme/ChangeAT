"""镜头子资源接口响应壳测试：细节 / 对白 / 分镜帧。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import app
from app.models.studio import (
    CameraAngle,
    CameraMovement,
    CameraShotType,
    Chapter,
    ChapterStatus,
    DialogueLineMode,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
    ShotDetail,
    ShotDialogLine,
    ShotFrameImage,
    ShotFrameType,
    ShotStatus,
    VFXType,
)


class _EmptyScalars:
    """空结果集替身：``scalars().first()`` 恒为 None。"""

    def first(self) -> None:
        return None


class _EmptyExecuteResult:
    """空查询结果替身：供假 DB 的 ``execute`` 返回。"""

    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()


class _FakeShotSubresourceDB:
    """最小 DB 替身：仅覆盖镜头子资源接口测试所需行为。"""

    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.chapters: dict[str, Chapter] = {}
        self.shots: dict[str, Shot] = {}
        self.shot_details: dict[str, ShotDetail] = {}
        self.dialog_lines: dict[int, ShotDialogLine] = {}
        self.frame_images: dict[int, ShotFrameImage] = {}
        self._line_id = 1
        self._frame_id = 1

    async def scalar(self, stmt):  # noqa: ANN001
        """模拟 router 级工作区守卫的归属查询。

        守卫（`app/api/scoping.py`）会对带 shot_id / line_id / image_id 的请求
        先做一次「实体是否存在且属于当前工作区」的查询。替身必须按主键回查，
        否则守卫会把所有子资源用例打成 404。

        只覆盖「按主键 + workspace_id 过滤」这一个形态，不做通用 SQL 解释；
        真正的越权语义由 `test_workspace_multitenancy.py` 用真实 DB 覆盖。
        """
        entity = stmt.column_descriptions[0]["entity"]
        stores = {
            Project: self.projects,
            Chapter: self.chapters,
            Shot: self.shots,
            ShotDetail: self.shot_details,
            ShotDialogLine: self.dialog_lines,
            ShotFrameImage: self.frame_images,
        }
        store = stores.get(entity)
        if store is None:
            return None
        params = stmt.compile().params
        pk = next((v for k, v in params.items() if k.split("_")[0] == "id"), None)
        if pk is None:
            return None
        obj = store.get(pk)
        if obj is None:
            return None
        expected_ws = next((v for k, v in params.items() if k.startswith("workspace_id")), None)
        if expected_ws is not None:
            owner = getattr(obj, "workspace_id", None)
            # 子资源本身没有 workspace_id，归属由其父级链路决定；
            # 替身里只要工作区过滤参数存在就视为通过。
            if owner is not None and owner != expected_ws:
                return None
        return obj

    async def get(self, model: type, entity_id):  # noqa: ANN001
        if model is Project:
            return self.projects.get(entity_id)
        if model is Chapter:
            return self.chapters.get(entity_id)
        if model is Shot:
            return self.shots.get(entity_id)
        if model is ShotDetail:
            return self.shot_details.get(entity_id)
        if model is ShotDialogLine:
            return self.dialog_lines.get(entity_id)
        if model is ShotFrameImage:
            return self.frame_images.get(entity_id)
        return None

    def add(self, obj: object) -> None:
        if isinstance(obj, Project):
            self.projects[obj.id] = obj
            return
        if isinstance(obj, Chapter):
            self.chapters[obj.id] = obj
            return
        if isinstance(obj, Shot):
            self.shots[obj.id] = obj
            return
        if isinstance(obj, ShotDetail):
            self.shot_details[obj.id] = obj
            return
        if isinstance(obj, ShotDialogLine):
            if getattr(obj, "id", None) is None:
                obj.id = self._line_id
                self._line_id += 1
            self.dialog_lines[obj.id] = obj
            return
        if isinstance(obj, ShotFrameImage):
            if getattr(obj, "id", None) is None:
                obj.id = self._frame_id
                self._frame_id += 1
            self.frame_images[obj.id] = obj
            return
        raise TypeError(f"Unsupported object type: {type(obj)!r}")

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        obj.updated_at = now

    async def delete(self, obj: object) -> None:
        if isinstance(obj, ShotDetail):
            self.shot_details.pop(obj.id, None)
            return
        if isinstance(obj, ShotDialogLine):
            self.dialog_lines.pop(obj.id, None)
            return
        if isinstance(obj, ShotFrameImage):
            self.frame_images.pop(obj.id, None)
            return
        raise TypeError(f"Unsupported object type: {type(obj)!r}")

    async def execute(self, *_args, **_kwargs):  # noqa: ANN001
        """返回空结果集：替身未维护「提取候选」表，故无候选需要回退。"""
        return _EmptyExecuteResult()


def _override_db(db: _FakeShotSubresourceDB):
    async def _get_db() -> AsyncGenerator[_FakeShotSubresourceDB, None]:
        yield db

    return _get_db


def _seed_project_and_shot(db: _FakeShotSubresourceDB) -> None:
    now = datetime.now(UTC)
    project = Project(
        workspace_id="ws-test",
        id="proj-1",
        name="测试项目",
        description="项目说明",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
        seed=1,
        unify_style=True,
        progress=0,
        stats={},
    )
    project.created_at = now
    project.updated_at = now
    db.projects[project.id] = project

    chapter = Chapter(
        id="ch-1",
        project_id=project.id,
        index=1,
        title="第一章",
        summary="章节摘要",
        raw_text="原文",
        condensed_text="精简原文",
        storyboard_count=0,
        status=ChapterStatus.draft,
    )
    chapter.created_at = now
    chapter.updated_at = now
    db.chapters[chapter.id] = chapter

    shot = Shot(
        id="shot-1",
        chapter_id=chapter.id,
        index=1,
        title="镜头一",
        thumbnail="",
        status=ShotStatus.pending,
        script_excerpt="剧本摘录",
        generated_video_file_id=None,
    )
    shot.created_at = now
    shot.updated_at = now
    db.shots[shot.id] = shot


def _seed_shot_detail(db: _FakeShotSubresourceDB, shot_id: str = "shot-1") -> ShotDetail:
    now = datetime.now(UTC)
    detail = ShotDetail(
        id=shot_id,
        camera_shot=CameraShotType.ms,
        angle=CameraAngle.eye_level,
        movement=CameraMovement.static,
        scene_id=None,
        duration=4,
        mood_tags=[],
        atmosphere="",
        follow_atmosphere=True,
        has_bgm=False,
        vfx_type=VFXType.none,
        vfx_note="",
        description="",
        prompt_template_id=None,
        first_frame_prompt="",
        last_frame_prompt="",
        key_frame_prompt="",
    )
    detail.created_at = now
    detail.updated_at = now
    db.shot_details[detail.id] = detail
    return detail


def test_create_shot_detail_returns_created_envelope(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    _seed_project_and_shot(db)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shot-details",
            json={
                "id": "shot-1",
                "camera_shot": "MS",
                "angle": "EYE_LEVEL",
                "movement": "STATIC",
                "scene_id": None,
                "duration": 4,
                "mood_tags": [],
                "atmosphere": "",
                "follow_atmosphere": True,
                "has_bgm": False,
                "vfx_type": "NONE",
                "vfx_note": "",
                "first_frame_prompt": "",
                "last_frame_prompt": "",
                "key_frame_prompt": "",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["data"]["id"] == "shot-1"


def test_get_shot_detail_not_found_returns_api_response(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/shot-details/missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "ShotDetail not found", "data": None, "meta": None}


def test_delete_shot_detail_returns_empty_envelope(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    _seed_project_and_shot(db)
    _seed_shot_detail(db)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/shot-details/shot-1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "success", "data": None, "meta": None}
    assert "shot-1" not in db.shot_details


def test_create_shot_dialog_line_returns_created_envelope(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    _seed_project_and_shot(db)
    _seed_shot_detail(db)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shot-dialog-lines",
            json={
                "shot_detail_id": "shot-1",
                "index": 1,
                "text": "你好",
                "line_mode": "DIALOGUE",
                "speaker_character_id": None,
                "target_character_id": None,
                "speaker_name": None,
                "target_name": None,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["data"]["text"] == "你好"
    assert body["data"]["id"] == 1


def test_update_shot_dialog_line_not_found_returns_api_response(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.patch(
            "/api/v1/studio/shot-dialog-lines/999",
            json={"text": "更新后的台词"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "ShotDialogLine not found", "data": None, "meta": None}


def test_delete_shot_dialog_line_returns_empty_envelope(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    _seed_project_and_shot(db)
    _seed_shot_detail(db)
    line = ShotDialogLine(
        shot_detail_id="shot-1",
        index=1,
        text="你好",
        line_mode=DialogueLineMode.dialogue,
        speaker_character_id=None,
        target_character_id=None,
        speaker_name=None,
        target_name=None,
    )
    line.id = 1
    line.created_at = datetime.now(UTC)
    line.updated_at = line.created_at
    db.dialog_lines[line.id] = line
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/shot-dialog-lines/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "success", "data": None, "meta": None}
    assert 1 not in db.dialog_lines


def test_create_shot_frame_image_returns_created_envelope(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    _seed_project_and_shot(db)
    _seed_shot_detail(db)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shot-frame-images",
            json={
                "shot_detail_id": "shot-1",
                "frame_type": "first",
                "file_id": None,
                "width": 1280,
                "height": 720,
                "format": "png",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["data"]["id"] == 1
    assert body["data"]["frame_type"] == "first"


def test_update_shot_frame_image_not_found_returns_api_response(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.patch(
            "/api/v1/studio/shot-frame-images/999",
            json={"format": "jpg"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "ShotFrameImage not found", "data": None, "meta": None}


def test_delete_shot_frame_image_returns_empty_envelope(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    _seed_project_and_shot(db)
    _seed_shot_detail(db)
    frame = ShotFrameImage(
        shot_detail_id="shot-1",
        frame_type=ShotFrameType.first,
        file_id=None,
        width=1280,
        height=720,
        format="png",
    )
    frame.id = 1
    frame.created_at = datetime.now(UTC)
    frame.updated_at = frame.created_at
    db.frame_images[frame.id] = frame
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/shot-frame-images/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "success", "data": None, "meta": None}
    assert 1 not in db.frame_images


def test_create_shot_detail_validation_error_returns_api_response(client: TestClient) -> None:
    db = _FakeShotSubresourceDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shot-details",
            json={
                "id": "shot-invalid",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert body["data"] is None
    assert "camera_shot" in body["message"]
    assert "angle" in body["message"]
    assert "movement" in body["message"]
