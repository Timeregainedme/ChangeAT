from __future__ import annotations

"""音频（TTS）生成任务 API。

通过 TaskManager 调用 `AudioGenerationTask`，并用 `GenerationTaskLink`
（resource_type="audio"）建立任务与上层业务实体的关联。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.audio_generation import AudioFormat, AudioVoiceSource
from app.dependencies import get_db
from app.schemas.common import ApiResponse, created_response, success_response
from app.api.v1.routes.film.common import TaskCreated
from app.services.studio.audio_task_runner import create_audio_task_and_link as _create_audio_task_and_link_service
from app.services.studio.audio_tasks import load_audio_provider_config, resolve_audio_model


router = APIRouter()

COMPTSHARE_PROVIDER_KEY = "compshare_model_api"


class StudioAudioTaskRequest(BaseModel):
    """Studio 专用音频任务请求体：可选模型 ID，不传则用默认音频模型；供应商由模型反查。

    两种用法：
    - 传 `text`（可配 `voice`）生成一段独立音频；
    - 传 `dialog_line_id` 为某句台词配音：文本、说话角色、挂载目标自动带出，
      音色取该角色的默认音色，产物直接挂到这句台词上（一个分镜多句台词互不覆盖）。
    """

    model_id: str | None = Field(None, description="音频模型 ID；不传则使用默认音频模型")
    text: str | None = Field(
        None,
        min_length=1,
        description="待合成文本；传 dialog_line_id 时可省略（自动复用台词文本）",
    )
    dialog_line_id: int | None = Field(
        None,
        description="台词行 ID：按该行台词配音，文本/说话角色/挂载目标自动带出",
    )
    speaker_character_id: str | None = Field(
        None,
        description="说话角色 ID：用于解析角色默认音色，不传则从台词行带出",
    )
    voice: str | None = Field(None, description="音色 ID；不传则取说话角色配置的默认音色")
    voice_source: AudioVoiceSource | None = Field(
        None,
        description="音色来源：preset=预置音色、custom=复刻音色；不传则按模型名推断",
    )
    language: str | None = Field(None, description="语种，如 zh / en / ja；不传默认中文")
    speed: float | None = Field(None, ge=0.0, description="语速倍率，仅大于 0 时下发")
    emotion: str | None = Field(None, max_length=200, description="情感描述文本")
    format: AudioFormat = Field("wav", description="输出音频格式")
    relation_type: str = Field(
        "",
        max_length=32,
        description="业务关联类型：留空则由服务端推导（shot/dialog_line/standalone）",
    )
    relation_entity_id: str = Field("", max_length=64, description="业务关联实体 ID")
    project_id: str | None = Field(None, description="可选：归属项目 ID，用于登记文件使用位置")
    chapter_id: str | None = Field(None, description="可选：归属章节 ID")
    shot_id: str | None = Field(None, description="可选：归属镜头 ID")


class VoiceItem(BaseModel):
    voice_id: str = Field("", description="音色 ID")
    name: str = Field("", description="音色显示名")
    language: str | None = Field(None, description="语种")
    raw: dict = Field(default_factory=dict, description="供应商原始字段")


@router.post(
    "/speech",
    response_model=ApiResponse[TaskCreated],
    status_code=status.HTTP_201_CREATED,
)
async def create_speech_task(
    body: StudioAudioTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskCreated]:
    """创建语音合成任务（异步轮询）。

    参数在请求期即按供应商能力校验（评审 R-20），非法参数返回 422 而不是先建任务再失败。
    """
    task_id = await _create_audio_task_and_link_service(
        db=db,
        model_id=body.model_id,
        text=body.text,
        dialog_line_id=body.dialog_line_id,
        speaker_character_id=body.speaker_character_id,
        relation_type=body.relation_type,
        relation_entity_id=body.relation_entity_id or "",
        voice=body.voice,
        voice_source=body.voice_source,
        language=body.language,
        speed=body.speed,
        emotion=body.emotion,
        audio_format=body.format,
        project_id=body.project_id,
        chapter_id=body.chapter_id,
        shot_id=body.shot_id,
    )
    return created_response(TaskCreated(task_id=task_id))


@router.get(
    "/voices",
    response_model=ApiResponse[list[VoiceItem]],
)
async def list_audio_voices(
    model_id: str | None = Query(None, description="音频模型 ID；不传则使用默认音频模型"),
    kind: str = Query("preset", description="音色类型：preset 或 custom"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[VoiceItem]]:
    """查询供应商可用音色（当前仅优云智算 IndexTTS 支持）。"""
    model = await resolve_audio_model(db, model_id)
    provider_cfg = await load_audio_provider_config(db, model.provider_id)
    if provider_cfg.provider != COMPTSHARE_PROVIDER_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider {provider_cfg.provider!r} does not expose a voice list API",
        )

    from app.core.integrations.compshare.audio import CompshareAudioApiAdapter

    adapter = CompshareAudioApiAdapter()
    items = await adapter.list_voices(cfg=provider_cfg, kind=kind)

    out: list[VoiceItem] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        out.append(
            VoiceItem(
                voice_id=str(row.get("voice_id") or row.get("id") or row.get("voice") or ""),
                name=str(row.get("name") or row.get("label") or ""),
                language=(str(row.get("language") or "").strip() or None),
                raw=row,
            )
        )
    return success_response(out)
