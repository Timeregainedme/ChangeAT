"""给 Celery worker 使用的同步任务执行服务。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chains.agents import ElementExtractorAgent, ScriptDividerAgent
from app.chains.agents import (
    CharacterPortraitAnalysisAgent,
    ConsistencyCheckerAgent,
    CostumeInfoAnalysisAgent,
    PropInfoAnalysisAgent,
    SceneInfoAnalysisAgent,
    ScriptOptimizerAgent,
    ScriptSimplifierAgent,
)
from app.chains.agents.script_processing_agents import (
    ScriptConsistencyCheckResult,
    ScriptDivisionResult,
    ScriptOptimizationResult,
    ScriptSimplificationResult,
)
from app.core.db_sync import sync_session_maker
from app.models.studio_shots import Shot
from app.services.script_extraction_cache import (
    build_script_extract_cache_key,
    get_cached_script_extract,
    set_cached_script_extract,
)
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.studio.script_division import write_division_result_to_chapter_sync
from app.services.studio.shot_extracted_candidates import (
    sync_from_extraction_draft_sync as sync_shot_extracted_candidates_from_draft_sync,
)
from app.services.studio.shot_extracted_dialogue_candidates import (
    sync_from_extraction_draft_sync as sync_shot_extracted_dialogue_candidates_from_draft_sync,
)
from app.services.studio.shot_semantic_defaults import apply_shot_semantic_defaults_from_draft_sync
from app.services.worker.task_executor import (
    AbstractLLMResultGenerator,
    AbstractWorkerTaskExecutor,
    WorkerTaskContext,
)


logger = logging.getLogger(__name__)


class DivideResultGenerator(AbstractLLMResultGenerator):
    thinking = False

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptDivisionResult:
        agent = ScriptDividerAgent(llm)
        return agent.divide_script(script_text=str(run_args.get("script_text") or ""))


class ExtractResultGenerator(AbstractLLMResultGenerator):
    thinking = False

    def generate(self, db: Session, run_args: dict[str, Any]) -> tuple[Any, bool]:
        return generate_extraction_result(
            db=db,
            project_id=str(run_args.get("project_id") or ""),
            chapter_id=str(run_args.get("chapter_id") or ""),
            script_division=dict(run_args.get("script_division") or {}),
            consistency=dict(run_args.get("consistency") or {}) if run_args.get("consistency") else None,
            refresh_cache=bool(run_args.get("refresh_cache")),
        )

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:  # pragma: no cover - 不直接走这里
        raise NotImplementedError


class ConsistencyResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptConsistencyCheckResult:
        agent = ConsistencyCheckerAgent(llm)
        return agent.extract(script_text=str(run_args.get("script_text") or ""))


class CharacterPortraitResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = CharacterPortraitAnalysisAgent(llm)
        return agent.analyze_character_description(
            character_context=run_args.get("character_context"),
            character_description=str(run_args.get("character_description") or ""),
        )


class PropInfoResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = PropInfoAnalysisAgent(llm)
        return agent.analyze_prop_description(
            prop_context=run_args.get("prop_context"),
            prop_description=str(run_args.get("prop_description") or ""),
        )


class SceneInfoResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = SceneInfoAnalysisAgent(llm)
        return agent.analyze_scene_description(
            scene_context=run_args.get("scene_context"),
            scene_description=str(run_args.get("scene_description") or ""),
        )


class CostumeInfoResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = CostumeInfoAnalysisAgent(llm)
        return agent.analyze_costume_description(
            costume_context=run_args.get("costume_context"),
            costume_description=str(run_args.get("costume_description") or ""),
        )


class ScriptOptimizationResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptOptimizationResult:
        agent = ScriptOptimizerAgent(llm)
        return agent.extract(
            script_text=str(run_args.get("script_text") or ""),
            consistency_json=json.dumps(dict(run_args.get("consistency") or {}), ensure_ascii=False),
        )


class ScriptSimplificationResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptSimplificationResult:
        agent = ScriptSimplifierAgent(llm)
        return agent.extract(script_text=str(run_args.get("script_text") or ""))


class DivideTaskExecutor(AbstractWorkerTaskExecutor):
    task_kind = "script_divide"
    timeout_seconds = 1800.0

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = DivideResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> ScriptDivisionResult:
        return self._generator.generate(ctx.db, run_args)

    def should_apply(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: ScriptDivisionResult) -> bool:  # noqa: ARG002
        return bool(run_args.get("write_to_db"))

    def apply_result(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: ScriptDivisionResult) -> None:
        chapter_id = str(run_args.get("chapter_id") or "")
        if not chapter_id:
            raise HTTPException(status_code=400, detail="chapter_id is required for write_to_db=true")
        apply_division_result(ctx.db, chapter_id=chapter_id, result=result)


class ExtractTaskExecutor(AbstractWorkerTaskExecutor):
    task_kind = "script_extract"
    timeout_seconds = 1800.0

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = ExtractResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> tuple[Any, bool]:
        return self._generator.generate(ctx.db, run_args)

    def serialize_result(self, result: tuple[Any, bool]) -> dict[str, Any]:
        draft, from_cache = result
        return {
            "draft": draft.model_dump(),
            "from_cache": from_cache,
        }

    def should_apply(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: tuple[Any, bool]) -> bool:  # noqa: ARG002
        return True

    def apply_result(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: tuple[Any, bool]) -> None:
        draft, _from_cache = result
        chapter_id = str(run_args.get("chapter_id") or "")
        apply_extraction_result(ctx.db, chapter_id=chapter_id, draft=draft)


class ConsistencyTaskExecutor(AbstractWorkerTaskExecutor):
    task_kind = "script_consistency"
    succeeded_progress = 100
    timeout_seconds = 900.0

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = ConsistencyResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> ScriptConsistencyCheckResult:
        return self._generator.generate(ctx.db, run_args)


class _SimpleLLMTaskExecutor(AbstractWorkerTaskExecutor):
    succeeded_progress = 100
    timeout_seconds = 900.0
    generator_class: type[AbstractLLMResultGenerator]

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = self.generator_class()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> Any:
        return self._generator.generate(ctx.db, run_args)


class CharacterPortraitTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_character_portrait"
    generator_class = CharacterPortraitResultGenerator


class PropInfoTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_prop_info"
    generator_class = PropInfoResultGenerator


class SceneInfoTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_scene_info"
    generator_class = SceneInfoResultGenerator


class CostumeInfoTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_costume_info"
    generator_class = CostumeInfoResultGenerator


class ScriptOptimizationTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_optimize"
    generator_class = ScriptOptimizationResultGenerator


class ScriptSimplificationTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_simplify"
    generator_class = ScriptSimplificationResultGenerator


def generate_division_result(
    *,
    db: Session,
    script_text: str,
) -> ScriptDivisionResult:
    llm = build_default_text_llm_sync(db, thinking=False)
    agent = ScriptDividerAgent(llm)
    return agent.divide_script(script_text=script_text)


def apply_division_result(
    db: Session,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    write_division_result_to_chapter_sync(db, chapter_id=chapter_id, result=result)


def _rebuild_script_division_from_shots(db: Session, chapter_id: str) -> dict[str, Any]:
    """从库内分镜重建 script_division。

    extract-async 契约允许前端传空 ``script_division``（见 ChapterPrep 注释
    「服务端从库内分镜重建」）；此前后端直接透传空 dict，导致 LLM 提取
    拿到空输入、候选/资产全为空。这里按 divide 落库的 shots 重建分镜结构。
    """

    shots = db.execute(
        select(Shot).where(Shot.chapter_id == chapter_id).order_by(Shot.index)
    ).scalars().all()
    if not shots:
        return {"shots": [], "total_shots": 0}
    division_shots = []
    for shot in shots:
        division_shots.append(
            {
                "index": shot.index,
                "start_line": shot.index,  # 库内不存原始行号，用序号近似（LLM 提取主要依赖 script_excerpt）
                "end_line": shot.index,
                "script_excerpt": shot.script_excerpt or "",
                "shot_name": shot.title or "",
            }
        )
    return {"shots": division_shots, "total_shots": len(division_shots)}


def generate_extraction_result(
    *,
    db: Session,
    project_id: str,
    chapter_id: str,
    script_division: dict[str, Any],
    consistency: dict[str, Any] | None,
    refresh_cache: bool,
) -> tuple[Any, bool]:
    # 前端契约：script_division 可为空，服务端从库内分镜重建后再提取。
    if not script_division.get("shots"):
        script_division = _rebuild_script_division_from_shots(db, chapter_id)

    cache_key = build_script_extract_cache_key(
        project_id=project_id,
        chapter_id=chapter_id,
        script_division=script_division,
        consistency=consistency,
    )

    result = None
    from_cache = False
    if not refresh_cache:
        result = get_cached_script_extract(cache_key)
        from_cache = result is not None

    if result is None:
        llm = build_default_text_llm_sync(db, thinking=False)
        agent = ElementExtractorAgent(llm)
        result = agent.extract(
            project_id=project_id,
            chapter_id=chapter_id,
            script_division_json=json.dumps(script_division, ensure_ascii=False),
            consistency_json=json.dumps(consistency or {}, ensure_ascii=False),
        )
        set_cached_script_extract(cache_key, result)

    return result, from_cache


def apply_extraction_result(
    db: Session,
    *,
    chapter_id: str,
    draft: Any,
) -> None:
    """将提取草稿同步为候选与镜头语言默认值。"""

    sync_shot_extracted_candidates_from_draft_sync(db, chapter_id=chapter_id, draft=draft)
    sync_shot_extracted_dialogue_candidates_from_draft_sync(db, chapter_id=chapter_id, draft=draft)
    apply_shot_semantic_defaults_from_draft_sync(db, chapter_id=chapter_id, draft=draft)


def run_divide_task_sync(task_id: str) -> None:
    DivideTaskExecutor().run(task_id)


def run_extract_task_sync(task_id: str) -> None:
    ExtractTaskExecutor().run(task_id)


def run_consistency_task_sync(task_id: str) -> None:
    ConsistencyTaskExecutor().run(task_id)


def run_character_portrait_task_sync(task_id: str) -> None:
    CharacterPortraitTaskExecutor().run(task_id)


def run_prop_info_task_sync(task_id: str) -> None:
    PropInfoTaskExecutor().run(task_id)


def run_scene_info_task_sync(task_id: str) -> None:
    SceneInfoTaskExecutor().run(task_id)


def run_costume_info_task_sync(task_id: str) -> None:
    CostumeInfoTaskExecutor().run(task_id)


def run_script_optimization_task_sync(task_id: str) -> None:
    ScriptOptimizationTaskExecutor().run(task_id)


def run_script_simplification_task_sync(task_id: str) -> None:
    ScriptSimplificationTaskExecutor().run(task_id)
