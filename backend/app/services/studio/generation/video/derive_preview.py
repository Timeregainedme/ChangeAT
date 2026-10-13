from __future__ import annotations

from app.chains.prompts.ir import (
    MAX_REFERENCE_IMAGES,
    IRPrompt,
    build_video_prompt_ir,
    dialogues_from_summary,
)
from app.chains.prompts.renderers import uses_h3_prompt_format
from app.chains.prompts.renderers.h3 import H3Prose, render_h3
from app.schemas.studio.shots import ShotVideoPromptPackRead, ShotVideoPromptPreviewRead
from app.services.studio.generation.shared.types import GenerationDerivedPreview
from app.services.studio.generation.video.build_base import VideoBaseDraft
from app.services.studio.generation.video.build_context import (
    REFERENCE_MODE,
    VideoGenerationContext,
)
from app.services.studio.shot_video_prompt_pack import (
    _fallback_video_prompt,
    _pack_variables,
    _render_template,
    _resolve_video_prompt_template,
    build_shot_video_prompt_pack,
    enrich_rendered_video_prompt,
)


class VideoDerivedPreview(GenerationDerivedPreview):
    """视频生成预览结果。"""

    kind: str = "video"
    shot_id: str
    reference_mode: str
    rendered_prompt: str
    images: list[str]
    pack: ShotVideoPromptPackRead
    template_id: str | None = None
    template_name: str | None = None


def _build_ir(pack: ShotVideoPromptPackRead, context: VideoGenerationContext) -> IRPrompt:
    return build_video_prompt_ir(
        pack,
        dialogues=dialogues_from_summary(pack.dialogue_summary),
        duration_seconds=pack.camera.duration,
        aspect_ratio=context.ratio or None,
        max_references=MAX_REFERENCE_IMAGES,
    )


def _reference_file_ids(ir: IRPrompt) -> list[str]:
    return [str(ref.file_id) for ref in ir.references if ref.file_id]


async def resolve_reference_mode_file_ids(
    db,
    *,
    shot_id: str,
    ratio: str | None = None,
) -> list[str]:
    """参考图模式下由服务端解析参考图顺序，客户端不需要、也不应该自己编号。

    上传顺序必须与提示词里的 `<Picture N>` 一一对应，而两者都由同一份 IR 生成；
    所以客户端不传 `images` 时这里直接补全，避免「先开预览才有参考图」的隐式耦合。
    """
    pack = await build_shot_video_prompt_pack(db, shot_id=shot_id)
    context = VideoGenerationContext(
        shot_id=shot_id,
        reference_mode=REFERENCE_MODE,
        images=[],
        ratio=ratio or "",
    )
    return _reference_file_ids(_build_ir(pack, context))


async def _generate_h3_prose(db, ir: IRPrompt) -> tuple[H3Prose | None, list[str]]:
    """用默认文本模型把 IR 写成 H3 英文正文；任何失败都降级为结构骨架。"""
    from app.chains.agents.h3_video_prompt_agent import generate_h3_prose

    run_sync = getattr(db, "run_sync", None)
    if not callable(run_sync):
        return None, ["当前会话不支持构建文本模型，H3 英文正文已回落为结构骨架"]
    try:
        from app.services.llm.runtime import build_default_text_llm_sync

        llm = await run_sync(
            lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
        )
    except Exception as exc:  # noqa: BLE001 - 文本模型不可用时不应阻断视频生成链路
        return None, [f"未取得文本模型，H3 英文正文已回落为结构骨架：{exc}"]
    return await generate_h3_prose(llm, ir)


async def _render_with_model_prompt_format(
    db,
    *,
    ir: IRPrompt,
    pack: ShotVideoPromptPackRead,
    context: VideoGenerationContext,
) -> tuple[str, list[str]]:
    """未配置视频提示词模板时：走 IR + 目标模型的提示词渲染器。

    这样「换模型只加渲染器」：IR 与业务链路无关，方言由 `renderers/` 决定。
    """
    warnings = list(ir.warnings)

    if not uses_h3_prompt_format(provider=context.provider, model=context.model):
        warnings.append(
            f"视频模型 {context.provider or '-'}/{context.model or '-'} 未登记专用提示词格式，"
            "已使用系统默认拼装提示词"
        )
        return _fallback_video_prompt(pack), warnings

    prose, prose_warnings = await _generate_h3_prose(db, ir)
    warnings.extend(prose_warnings)

    result = render_h3(ir, prose=prose)
    warnings.extend(result.warnings)
    return result.text, warnings


async def derive_video_preview(
    db,
    *,
    base: VideoBaseDraft,
    context: VideoGenerationContext,
) -> VideoDerivedPreview:
    pack = await build_shot_video_prompt_pack(db, shot_id=base.shot_id)
    ir = _build_ir(pack, context)

    # 参考图模式下不使用分镜帧：素材一律取 IR 的有序参考列表，
    # 保证上传的第 N 张图恰好对应提示词里的 <Picture N>。
    images = (
        _reference_file_ids(ir)
        if context.reference_mode == REFERENCE_MODE
        else list(context.images)
    )

    if base.prompt:
        rendered_prompt = enrich_rendered_video_prompt(
            rendered_prompt=base.prompt,
            pack=pack,
        )
        return VideoDerivedPreview(
            shot_id=base.shot_id,
            reference_mode=context.reference_mode,
            rendered_prompt=rendered_prompt,
            images=images,
            pack=pack,
            template_id=context.template_id,
            template_name=None,
            warnings=list(ir.warnings) if context.reference_mode == REFERENCE_MODE else [],
        )

    template = await _resolve_video_prompt_template(db, template_id=context.template_id)
    warnings: list[str] = []
    if template is None:
        rendered_prompt, model_warnings = await _render_with_model_prompt_format(
            db,
            ir=ir,
            pack=pack,
            context=context,
        )
        warnings.extend(model_warnings)
    else:
        rendered_prompt = _render_template(template.content, _pack_variables(pack))
        if not rendered_prompt:
            warnings.append("视频提示词模板渲染结果为空，已使用系统默认拼装提示词")
            rendered_prompt = _fallback_video_prompt(pack)
        else:
            rendered_prompt = enrich_rendered_video_prompt(
                rendered_prompt=rendered_prompt,
                pack=pack,
            )

    return VideoDerivedPreview(
        shot_id=base.shot_id,
        reference_mode=context.reference_mode,
        rendered_prompt=rendered_prompt.strip(),
        images=images,
        pack=pack,
        template_id=template.id if template else None,
        template_name=template.name if template else None,
        warnings=warnings,
    )


def to_shot_video_prompt_preview_read(
    *,
    derived: VideoDerivedPreview,
) -> ShotVideoPromptPreviewRead:
    return ShotVideoPromptPreviewRead(
        shot_id=derived.shot_id,
        template_id=derived.template_id,
        template_name=derived.template_name,
        rendered_prompt=derived.rendered_prompt,
        pack=derived.pack,
        warnings=derived.warnings,
    )
