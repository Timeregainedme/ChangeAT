"""项目开工预检服务。

把「开工前必须确认的事」聚合成一次只读检查，覆盖用户既定的开工流程：
用哪个 api/模型、短剧风格与比例、每角色一个音色、分镜必须挂参考图、提取必须确认。

该服务不写入任何状态，只回答「现在能不能开工、缺什么」。
"""

from __future__ import annotations

from typing import get_args

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.image_generation import (
    DEFAULT_IMAGE_OUTPUT_FORMAT,
    ImageResolutionProfile,
)
from app.core.contracts.video_generation import VideoRatio
from app.core.integrations.image_capabilities import (
    DEFAULT_VIDEO_REFERENCE_RATIO_SIZE_MAP,
    resolve_image_capability,
)
from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.models.studio import (
    Actor,
    Chapter,
    Character,
    Project,
    Shot,
    ShotCandidateStatus,
    ShotDetail,
    ShotDialogueCandidateStatus,
    ShotExtractedCandidate,
    ShotExtractedDialogueCandidate,
    ShotFrameImage,
)
from app.schemas.studio.projects import (
    ProjectProductionReadinessCheck,
    ProjectProductionReadinessRead,
)
from app.services.common import entity_not_found
from app.services.llm.provider_registry import resolve_provider_key_from_name


_VALID_VIDEO_RATIOS = set(get_args(VideoRatio))
_VALID_IMAGE_RESOLUTION_PROFILES = set(get_args(ImageResolutionProfile))


def _enum_text(value: object) -> str:
    """把枚举或字符串统一成可读文本。

    ORM 取出的列值可能是枚举实例，也可能是普通字符串（取决于列类型与方言），
    直接访问 `.value` 会在后者上抛 AttributeError，因此这里做一次容错。
    """
    return str(getattr(value, "value", value) or "")


def _ck(
    key: str,
    label: str,
    ok: bool,
    message: str,
    detail: dict | None = None,
) -> ProjectProductionReadinessCheck:
    return ProjectProductionReadinessCheck(
        key=key,
        label=label,
        ok=ok,
        message=message,
        detail=detail or {},
    )


async def _model_check(
    db: AsyncSession,
    *,
    key: str,
    label: str,
    category: ModelCategoryKey,
    model_id: str | None,
) -> ProjectProductionReadinessCheck:
    """校验「默认模型 + 供应商 + api_key」这条链是否真的可用。"""
    if not model_id:
        return _ck(key, label, False, f"未配置默认{label}，请到模型管理里设置")
    model = await db.get(Model, model_id)
    if model is None:
        return _ck(key, label, False, f"默认{label}不存在：{model_id}", {"model_id": model_id})
    if model.category != category:
        return _ck(
            key,
            label,
            False,
            f"默认{label}类别不符：期望 {_enum_text(category)}，实际 {_enum_text(model.category)}",
            {"model_id": model_id},
        )
    provider = await db.get(Provider, model.provider_id)
    if provider is None:
        return _ck(key, label, False, f"{label}的供应商不存在：{model.provider_id}", {"model_id": model_id})
    if not (provider.api_key or "").strip():
        return _ck(
            key,
            label,
            False,
            f"供应商「{provider.name or provider.id}」尚未填写 API Key",
            {"provider_id": provider.id, "model_id": model_id},
        )
    return _ck(
        key,
        label,
        True,
        f"{provider.name or provider.id} / {model.name}",
        {"provider_id": provider.id, "model_id": model_id, "model_name": model.name},
    )


async def _image_output_check(
    db: AsyncSession,
    *,
    project: Project,
    image_model_id: str | None,
) -> ProjectProductionReadinessCheck:
    """校验图片输出规格：比例 → 分辨率档位 → 像素尺寸 → 容器格式。

    用户开工前必须确认「分辨率、图片格式」，但此前预检只校验视频比例；
    关键帧的 `resolution_profile`（standard/high，PIX 映射为 1K/2K）只活在前端 state 里，
    从未落库，预检完全看不到，用户只能等到真正跑图才发现档位/比例不对。

    这里按执行层同样的方式解析一遍，任何一步解析不出确定规格都判为未就绪，
    避免「预检全绿、一跑图就失败」。
    """
    key, label = "image_output_ready", "图片输出"
    if not image_model_id:
        return _ck(key, label, False, "未配置默认图片模型，无法确定图片输出规格")
    model = await db.get(Model, image_model_id)
    if model is None:
        return _ck(key, label, False, f"默认图片模型不存在：{image_model_id}", {"model_id": image_model_id})
    provider = await db.get(Provider, model.provider_id)
    if provider is None:
        return _ck(key, label, False, f"图片模型的供应商不存在：{model.provider_id}", {"model_id": image_model_id})

    provider_key = resolve_provider_key_from_name(provider.name or "")
    try:
        capability = resolve_image_capability(provider=provider_key, model=model.name)
    except ValueError as exc:
        return _ck(
            key,
            label,
            False,
            f"供应商 {provider_key or '<未设置>'} 没有注册图片能力，无法推导输出规格：{exc}",
            {"model_id": image_model_id, "provider": provider_key},
        )

    ratio_map = capability.ratio_size_profiles or DEFAULT_VIDEO_REFERENCE_RATIO_SIZE_MAP
    supported_ratios = set(capability.supported_ratios or ratio_map.keys())
    ratio = (project.default_image_ratio or "").strip() or (project.default_video_ratio or "").strip() or None
    profile = (
        (project.default_image_resolution_profile or "").strip()
        or (capability.default_resolution_profile or "").strip()
        or "standard"
    )
    detail: dict = {
        "provider": provider_key,
        "model_id": image_model_id,
        "model_name": model.name,
        "ratio": ratio,
        "resolution_profile": profile,
        "format": DEFAULT_IMAGE_OUTPUT_FORMAT,
    }

    if not ratio:
        return _ck(
            key,
            label,
            False,
            "项目未设置图片比例（default_image_ratio），也未设置 default_video_ratio，无法确定关键帧像素尺寸",
            detail,
        )
    if ratio not in supported_ratios:
        return _ck(
            key,
            label,
            False,
            f"图片比例 {ratio} 不被 {provider_key}/{model.name} 支持；允许值 {sorted(supported_ratios)}",
            detail,
        )
    if profile not in _VALID_IMAGE_RESOLUTION_PROFILES:
        return _ck(
            key,
            label,
            False,
            f"图片分辨率档位取值非法：{profile}；允许值 {sorted(_VALID_IMAGE_RESOLUTION_PROFILES)}",
            detail,
        )
    size = (ratio_map.get(ratio) or {}).get(profile)
    if not size:
        return _ck(
            key,
            label,
            False,
            (
                f"比例 {ratio} 下没有档位 {profile} 对应的像素尺寸；"
                f"可选档位 {sorted((ratio_map.get(ratio) or {}).keys())}"
            ),
            detail,
        )
    allowed_sizes = capability.allowed_sizes
    if allowed_sizes is not None and size not in allowed_sizes:
        return _ck(
            key,
            label,
            False,
            f"{provider_key}/{model.name} 的档位 {profile} 解析出 {size}，但该模型只接受 {sorted(allowed_sizes)}",
            {**detail, "size": size},
        )

    detail["size"] = size
    return _ck(
        key,
        label,
        True,
        (
            f"{provider.name or provider_key} / {model.name} · {ratio} · "
            f"{profile}({size}) · 输出 {DEFAULT_IMAGE_OUTPUT_FORMAT}"
        ),
        detail,
    )


async def _project_shot_ids(db: AsyncSession, *, project_id: str) -> list[str]:
    stmt = (
        select(Shot.id)
        .join(Chapter, Chapter.id == Shot.chapter_id)
        .where(Chapter.project_id == project_id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_project_production_readiness(
    db: AsyncSession,
    *,
    project_id: str,
) -> ProjectProductionReadinessRead:
    """聚合项目开工预检结果。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError(entity_not_found("Project"))

    settings = await db.get(ModelSettings, 1)
    text_model_id = settings.default_text_model_id if settings else None
    image_model_id = settings.default_image_model_id if settings else None
    video_model_id = settings.default_video_model_id if settings else None
    audio_model_id = settings.default_audio_model_id if settings else None
    checks: list[ProjectProductionReadinessCheck] = [
        await _model_check(
            db,
            key="text_model_ready",
            label="文本模型",
            category=ModelCategoryKey.text,
            model_id=text_model_id,
        ),
        await _model_check(
            db,
            key="image_model_ready",
            label="图片模型",
            category=ModelCategoryKey.image,
            model_id=image_model_id,
        ),
        await _model_check(
            db,
            key="video_model_ready",
            label="视频模型",
            category=ModelCategoryKey.video,
            model_id=video_model_id,
        ),
        await _model_check(
            db,
            key="audio_model_ready",
            label="音频模型",
            category=ModelCategoryKey.audio,
            model_id=audio_model_id,
        ),
        # 图片输出紧随图片模型：模型可用不代表输出规格可用（比例/档位/像素/格式都要能定下来）。
        await _image_output_check(db, project=project, image_model_id=image_model_id),
    ]

    # 短剧风格：题材与画面表现形式（数据库非空约束保证有值，这里只做显式回显与比例校验）。
    checks.append(
        _ck(
            "project_style_ready",
            "短剧风格",
            bool(project.style and project.visual_style),
            f"视觉风格 {_enum_text(project.visual_style)} / 题材风格 {_enum_text(project.style)}",
            {"visual_style": _enum_text(project.visual_style), "style": _enum_text(project.style)},
        )
    )

    shot_ids = await _project_shot_ids(db, project_id=project_id)
    shot_count = len(shot_ids)

    # 视频比例：请求参数 → 分镜覆盖 → 项目默认。
    # 注意 override_video_ratio 在 shot_details 表上（与 Shot 同主键），不是 shots 表的列。
    override_count = 0
    if shot_ids:
        override_stmt = select(func.count(ShotDetail.id)).where(
            ShotDetail.id.in_(shot_ids),
            ShotDetail.override_video_ratio.is_not(None),
            func.trim(ShotDetail.override_video_ratio) != "",
        )
        override_count = int(await db.scalar(override_stmt) or 0)

    project_ratio = (project.default_video_ratio or "").strip() or None
    if project_ratio and project_ratio not in _VALID_VIDEO_RATIOS:
        checks.append(
            _ck(
                "video_ratio_ready",
                "视频比例",
                False,
                f"项目默认比例取值非法：{project_ratio}；允许值 {sorted(_VALID_VIDEO_RATIOS)}",
                {"default_video_ratio": project_ratio},
            )
        )
    elif project_ratio:
        checks.append(
            _ck(
                "video_ratio_ready",
                "视频比例",
                True,
                f"项目默认比例 {project_ratio}",
                {"default_video_ratio": project_ratio, "shots_with_override": override_count},
            )
        )
    elif shot_count and override_count == shot_count:
        checks.append(
            _ck(
                "video_ratio_ready",
                "视频比例",
                True,
                f"项目未设默认比例，但 {override_count} 个分镜都已单独覆盖",
                {"default_video_ratio": None, "shots_with_override": override_count},
            )
        )
    else:
        checks.append(
            _ck(
                "video_ratio_ready",
                "视频比例",
                False,
                (
                    "项目未设置 default_video_ratio，"
                    f"且只有 {override_count}/{shot_count} 个分镜配置了覆盖比例，"
                    "未覆盖的分镜会直接报 ratio is required"
                ),
                {"default_video_ratio": None, "shots_with_override": override_count},
            )
        )

    # 每角色一个音色：生成台词配音时若无显式 voice，会先回落到角色音色，
    # 角色未配时再回落到它绑定的演员音色（sql/019-add-actor-voice.sql、评审 R-08 / m08247）。
    # 因此「已具备音色」= 角色自己配了 voice_id **或** 其演员配了 voice_id。
    char_stmt = select(func.count(Character.id)).where(Character.project_id == project_id)
    voice_stmt = (
        select(func.count(Character.id))
        .select_from(Character)
        .outerjoin(Actor, Actor.id == Character.actor_id)
        .where(
            Character.project_id == project_id,
            or_(
                and_(Character.voice_id.is_not(None), func.trim(Character.voice_id) != ""),
                and_(
                    Character.actor_id.is_not(None),
                    Actor.voice_id.is_not(None),
                    func.trim(Actor.voice_id) != "",
                ),
            ),
        )
    )
    character_count = int(await db.scalar(char_stmt) or 0)
    character_voice_count = int(await db.scalar(voice_stmt) or 0)
    if character_count == 0:
        checks.append(
            _ck("character_voice_ready", "角色音色", False, "项目下还没有角色，请先建角色卡", {"characters": 0})
        )
    else:
        missing = character_count - character_voice_count
        checks.append(
            _ck(
                "character_voice_ready",
                "角色音色",
                missing == 0,
                (
                    f"{character_voice_count}/{character_count} 个角色已具备音色（自带或来自演员）"
                    if missing == 0
                    else (
                        f"还有 {missing} 个角色既没有自己的 voice_id，"
                        "其绑定的演员也没有音色，配音时会因缺少音色而失败"
                    )
                ),
                {"characters": character_count, "with_voice": character_voice_count},
            )
        )

    # 分镜必须挂参考图：统计已挂帧的分镜数（任一帧有 file_id 即视为已挂）。
    framed_shot_count = 0
    if shot_ids:
        framed_stmt = select(func.count(func.distinct(ShotFrameImage.shot_detail_id))).where(
            ShotFrameImage.shot_detail_id.in_(shot_ids),
            ShotFrameImage.file_id.is_not(None),
        )
        framed_shot_count = int(await db.scalar(framed_stmt) or 0)
    if shot_count == 0:
        checks.append(
            _ck("shot_reference_frames_ready", "分镜参考图", False, "项目下还没有分镜", {"shots": 0})
        )
    else:
        unframed = shot_count - framed_shot_count
        checks.append(
            _ck(
                "shot_reference_frames_ready",
                "分镜参考图",
                unframed == 0,
                (
                    f"{shot_count} 个分镜均已挂参考图"
                    if unframed == 0
                    else f"还有 {unframed}/{shot_count} 个分镜未生成参考图"
                ),
                {"shots": shot_count, "with_reference_frames": framed_shot_count},
            )
        )

    # 提取必须确认：仍有待确认的资产/对白候选、或还有分镜从未跑过提取时，都不该开工。
    # 「从未提取」必须单独统计：分镜级就绪门禁要求 `Shot.last_extracted_at` 非空
    # （见 shot_video_readiness 的 extraction_ready），只数待确认候选会让预检通过、
    # 随后每个分镜在发起视频生成时被 409 拦住，预检就失去了预测作用。
    pending_assets = 0
    pending_dialogues = 0
    not_extracted_shots = 0
    if shot_ids:
        pending_assets = int(
            await db.scalar(
                select(func.count(ShotExtractedCandidate.id)).where(
                    ShotExtractedCandidate.shot_id.in_(shot_ids),
                    ShotExtractedCandidate.candidate_status == ShotCandidateStatus.pending,
                )
            )
            or 0
        )
        pending_dialogues = int(
            await db.scalar(
                select(func.count(ShotExtractedDialogueCandidate.id)).where(
                    ShotExtractedDialogueCandidate.shot_id.in_(shot_ids),
                    ShotExtractedDialogueCandidate.candidate_status == ShotDialogueCandidateStatus.pending,
                )
            )
            or 0
        )
        not_extracted_shots = int(
            await db.scalar(
                select(func.count(Shot.id)).where(
                    Shot.id.in_(shot_ids),
                    Shot.skip_extraction.is_(False),
                    Shot.last_extracted_at.is_(None),
                )
            )
            or 0
        )
    extraction_ok = pending_assets == 0 and pending_dialogues == 0 and not_extracted_shots == 0
    if not_extracted_shots:
        extraction_message = f"还有 {not_extracted_shots}/{shot_count} 个分镜未完成信息提取"
        if pending_assets or pending_dialogues:
            extraction_message += (
                f"；另有待确认项：资产 {pending_assets} 项，对白 {pending_dialogues} 项"
            )
    elif pending_assets or pending_dialogues:
        extraction_message = f"仍有待确认项：资产 {pending_assets} 项，对白 {pending_dialogues} 项"
    else:
        extraction_message = "提取结果已全部确认"
    checks.append(
        _ck(
            "extraction_confirmed_ready",
            "信息提取确认",
            extraction_ok,
            extraction_message,
            {
                "pending_assets": pending_assets,
                "pending_dialogues": pending_dialogues,
                "not_extracted_shots": not_extracted_shots,
            },
        )
    )

    chapter_count = int(
        await db.scalar(select(func.count(Chapter.id)).where(Chapter.project_id == project_id)) or 0
    )
    stats = {
        "chapters": chapter_count,
        "shots": shot_count,
        "shots_with_reference_frames": framed_shot_count,
        "characters": character_count,
        "characters_with_voice": character_voice_count,
    }

    return ProjectProductionReadinessRead(
        project_id=project_id,
        ready=all(item.ok for item in checks),
        checks=checks,
        stats=stats,
    )
