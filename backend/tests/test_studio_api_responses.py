"""Studio 主链路接口响应壳测试：projects / chapters / shots。"""

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
    Project,
    ProjectStyle,
    ProjectStyleOption,
    ProjectVisualStyle,
    Shot,
    ShotDetail,
    ShotStatus,
    VFXType,
)
from app.services.studio.shot_details import DEFAULT_SHOT_DURATION


class _FakeStudioDB:
    """最小 Studio DB 替身：仅覆盖项目/章节/镜头接口测试所需行为。"""

    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.chapters: dict[str, Chapter] = {}
        self.shots: dict[str, Shot] = {}
        self.shot_details: dict[str, ShotDetail] = {}
        # 风格目录：style-options 与项目创建校验都会读它
        self.style_options: dict[str, ProjectStyleOption] = {}

    async def get(self, model: type, entity_id: str):  # noqa: ANN001
        if model is Project:
            return self.projects.get(entity_id)
        if model is Chapter:
            return self.chapters.get(entity_id)
        if model is Shot:
            return self.shots.get(entity_id)
        if model is ShotDetail:
            return self.shot_details.get(entity_id)
        if model is ProjectStyleOption:
            return self.style_options.get(entity_id)
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
        if isinstance(obj, ProjectStyleOption):
            self.style_options[obj.id] = obj
            return
        raise TypeError(f"Unsupported object type: {type(obj)!r}")

    def add_all(self, objects: list[object]) -> None:
        """批量添加；不支持的类型静默忽略。

        响应壳测试只关心接口返回结构，不需要完整模拟 ORM；
        风格目录在首次访问时会用内置枚举种子化（`ensure_style_catalog`），
        这里只要把 `ProjectStyleOption` 放进来即可。
        """
        for obj in objects:
            try:
                self.add(obj)
            except TypeError:
                pass

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        """风格目录接口会在读取种子后提交，替身里无需真实事务。"""
        return None

    async def refresh(self, obj: object) -> None:
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        obj.updated_at = now

    async def delete(self, obj: object) -> None:
        if isinstance(obj, Project):
            self.projects.pop(obj.id, None)
            return
        if isinstance(obj, Chapter):
            self.chapters.pop(obj.id, None)
            return
        if isinstance(obj, Shot):
            self.shots.pop(obj.id, None)
            return
        if isinstance(obj, ShotDetail):
            self.shot_details.pop(obj.id, None)
            return
        raise TypeError(f"Unsupported object type: {type(obj)!r}")

    async def execute(self, _stmt):  # noqa: ANN001
        class _Scalars:
            def __init__(self, rows: list[object]) -> None:
                self._rows = rows

            def all(self) -> list[object]:
                return self._rows

        class _EmptyResult:
            def __init__(self, rows: list[object] | None = None) -> None:
                self._rows = rows or []

            def all(self) -> list[tuple]:
                return []

            def scalars(self) -> _Scalars:
                return _Scalars(self._rows)

        # 风格目录：list_style_options 走 execute(...).scalars().all()
        entity = _stmt.column_descriptions[0].get("entity")
        if entity is ProjectStyleOption:
            rows = sorted(self.style_options.values(), key=lambda item: item.sort_order)
            return _EmptyResult(rows)

        return _EmptyResult()

    async def scalar(self, stmt):  # noqa: ANN001
        """模拟 `select(X).where(X.id == ..., [X.workspace_id == ...])` 的取值。

        为什么不能直接返回 None：项目详情/删除接口已改为走 `db.scalar(...)` 做工作区
        归属校验（见 `app/api/scoping.py`），若替身不实现取值，所有涉及项目的用例都会
        变成 404，掩盖真实行为。

        实现方式：从编译后的绑定参数里取主键与 workspace_id 条件，回查内存字典。
        这只覆盖本文件用到的「按主键 + 工作区过滤」形态，不做通用 SQL 解释。
        """
        entity = stmt.column_descriptions[0]["entity"]
        stores = {
            Project: self.projects,
            Chapter: self.chapters,
            Shot: self.shots,
            ShotDetail: self.shot_details,
        }
        if entity is ProjectStyleOption:
            # ensure_style_catalog 用 `select(...).limit(1)` 判断是否已种子化
            return next(iter(self.style_options.values()), None)

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
            # 只有实体自身直接持有 workspace_id 时才比较（Project）；
            # Chapter / Shot 的归属经父级链路确定，替身里视为通过。
            if owner is not None and owner != expected_ws:
                return None
        return obj


def _override_db(db: _FakeStudioDB):
    async def _get_db() -> AsyncGenerator[_FakeStudioDB, None]:
        yield db

    return _get_db


def _seed_project(db: _FakeStudioDB, project_id: str = "proj-1") -> Project:
    now = datetime.now(UTC)
    obj = Project(
        workspace_id="ws-test",
        id=project_id,
        name="测试项目",
        description="项目说明",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
        seed=7,
        unify_style=True,
        progress=10,
        stats={},
    )
    obj.created_at = now
    obj.updated_at = now
    db.projects[obj.id] = obj
    return obj


def _seed_chapter(
    db: _FakeStudioDB,
    *,
    chapter_id: str = "ch-1",
    project_id: str = "proj-1",
) -> Chapter:
    now = datetime.now(UTC)
    obj = Chapter(
        id=chapter_id,
        project_id=project_id,
        index=1,
        title="第一章",
        summary="章节摘要",
        raw_text="原文",
        condensed_text="精简原文",
        storyboard_count=0,
        status=ChapterStatus.draft,
    )
    obj.created_at = now
    obj.updated_at = now
    db.chapters[obj.id] = obj
    return obj


def _seed_shot(
    db: _FakeStudioDB,
    *,
    shot_id: str = "shot-1",
    chapter_id: str = "ch-1",
) -> Shot:
    now = datetime.now(UTC)
    obj = Shot(
        id=shot_id,
        chapter_id=chapter_id,
        index=1,
        title="镜头一",
        thumbnail="",
        status=ShotStatus.pending,
        script_excerpt="剧本摘录",
        generated_video_file_id=None,
    )
    obj.created_at = now
    obj.updated_at = now
    db.shots[obj.id] = obj
    return obj


def test_create_project_returns_created_envelope(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/projects",
            json={
                "id": "proj-create",
                "name": "新项目",
                "description": "说明",
                "style": "真人都市",
                "visual_style": "现实",
                "seed": 1,
                "unify_style": True,
                "progress": 0,
                "stats": {},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["message"] == "success"
    assert body["data"]["id"] == "proj-create"
    assert body["data"]["name"] == "新项目"


def test_project_style_options_returns_grouped_choices(client: TestClient) -> None:
    # 风格目录已从枚举升级为表：接口会读 `project_styles`（首次访问自动种子化），
    # 因此这里必须用内存替身，否则会打到真实库并因缺表失败。
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/projects/style-options")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert "视觉" in body["data"]["visual_styles"][0]["label"] or body["data"]["visual_styles"][0]["value"] in {"现实", "动漫"}
    assert "现实" in body["data"]["styles_by_visual_style"]
    assert "动漫" in body["data"]["styles_by_visual_style"]
    assert "video_ratios" not in body["data"]
    assert "default_video_ratio" not in body["data"]


def test_create_project_rejects_invalid_style_combo(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/projects",
            json={
                "id": "proj-invalid-style",
                "name": "新项目",
                "description": "说明",
                "style": "真人都市",
                "visual_style": "动漫",
                "seed": 1,
                "unify_style": True,
                "progress": 0,
                "stats": {},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "style is not allowed for visual_style" in response.json()["message"]


def test_get_project_not_found_returns_api_response(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/projects/missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "Project not found", "data": None, "meta": None}


def test_delete_project_returns_empty_envelope(client: TestClient) -> None:
    db = _FakeStudioDB()
    _seed_project(db, "proj-delete")
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/projects/proj-delete")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "success", "data": None, "meta": None}
    assert "proj-delete" not in db.projects


def test_create_chapter_returns_created_envelope(client: TestClient) -> None:
    db = _FakeStudioDB()
    _seed_project(db, "proj-chapter")
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/chapters",
            json={
                "id": "ch-create",
                "project_id": "proj-chapter",
                "index": 1,
                "title": "第一章",
                "summary": "摘要",
                "raw_text": "原文",
                "condensed_text": "精简原文",
                "storyboard_count": 0,
                "status": "draft",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["data"]["id"] == "ch-create"
    assert body["data"]["project_id"] == "proj-chapter"


def test_create_chapter_missing_project_returns_api_response(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/chapters",
            json={
                "id": "ch-fail",
                "project_id": "proj-missing",
                "index": 1,
                "title": "第一章",
                "summary": "",
                "raw_text": "",
                "condensed_text": "",
                "storyboard_count": 0,
                "status": "draft",
            },
        )
    finally:
        app.dependency_overrides.clear()

    # 语义变更（多租户）：引用不存在的项目现在回 404 而非 400。
    # 原因：400 与「项目存在但不属于当前工作区」的 404 可区分，会泄露其他租户的
    # project_id 是否存在。文案保持 `Project not found` 不变，前端无需改动。
    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "Project not found", "data": None, "meta": None}


def test_get_chapter_not_found_returns_api_response(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/chapters/missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "Chapter not found", "data": None, "meta": None}


def test_create_shot_returns_created_envelope(client: TestClient) -> None:
    db = _FakeStudioDB()
    _seed_project(db, "proj-shot")
    _seed_chapter(db, chapter_id="ch-shot", project_id="proj-shot")
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shots",
            json={
                "id": "shot-create",
                "chapter_id": "ch-shot",
                "index": 1,
                "title": "镜头一",
                "thumbnail": "",
                "status": "pending",
                "script_excerpt": "镜头内容",
                "generated_video_file_id": None,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["data"]["id"] == "shot-create"
    assert body["data"]["chapter_id"] == "ch-shot"


def test_create_shot_also_creates_default_shot_detail(client: TestClient) -> None:
    """手工创建镜头必须同事务落下配套 ShotDetail。

    回归 P0：`shots.create()` 曾只建 Shot 不建 ShotDetail，导致手工创建的分镜在
    `preparation-state` / `shot-details` / `skip-extraction` 上一律 404，且写操作
    随事务回滚，分镜永久卡在 pending（只有「一键提取」产出的分镜带 detail）。
    """
    db = _FakeStudioDB()
    _seed_project(db, "proj-shot-detail")
    _seed_chapter(db, chapter_id="ch-shot-detail", project_id="proj-shot-detail")
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shots",
            json={
                "id": "shot-with-detail",
                "chapter_id": "ch-shot-detail",
                "index": 1,
                "title": "镜头一",
                "thumbnail": "",
                "status": "pending",
                "script_excerpt": "镜头内容",
                "generated_video_file_id": None,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    detail = db.shot_details.get("shot-with-detail")
    assert detail is not None, "创建镜头时没有落下配套 ShotDetail"
    assert detail.id == "shot-with-detail"
    assert detail.camera_shot is CameraShotType.ms
    assert detail.angle is CameraAngle.eye_level
    assert detail.movement is CameraMovement.static
    assert detail.vfx_type is VFXType.none
    assert detail.duration == DEFAULT_SHOT_DURATION


def test_get_shot_not_found_returns_api_response(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/shots/missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "Shot not found", "data": None, "meta": None}


def test_delete_shot_returns_empty_envelope(client: TestClient) -> None:
    db = _FakeStudioDB()
    _seed_project(db, "proj-shot-delete")
    _seed_chapter(db, chapter_id="ch-shot-delete", project_id="proj-shot-delete")
    _seed_shot(db, shot_id="shot-delete", chapter_id="ch-shot-delete")
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/shots/shot-delete")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "success", "data": None, "meta": None}
    assert "shot-delete" not in db.shots


def test_create_shot_validation_error_returns_api_response(client: TestClient) -> None:
    db = _FakeStudioDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post(
            "/api/v1/studio/shots",
            json={
                "id": "shot-invalid",
                "title": "缺字段镜头",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert body["data"] is None
    assert "chapter_id" in body["message"]
    assert "index" in body["message"]
