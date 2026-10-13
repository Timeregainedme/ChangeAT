"""IR 中间层与 H3 提示词渲染器的回归测试。

对应「提示词改造第 2 档」的 C（引入 IR 中间层）与 A1（H3 原生英文渲染器）。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.chains.agents.shot_frame_prompt_agents import (
    _SHOT_FRAME_INPUT_VARS,
    ShotFirstFramePromptAgent,
    ShotKeyFramePromptAgent,
    ShotLastFramePromptAgent,
    build_frame_prompt_template,
)
from app.chains.prompts import short_drama_rules as rules
from app.chains.prompts.ir import IRDialogueInput, build_video_prompt_ir
from app.chains.prompts.renderers.h3 import (
    BASE_SECTION_ORDER,
    REFERENCE_SECTION_ORDER,
    H3Prose,
    render_h3,
    render_h3_reference,
    validate_h3_reference,
)
from app.core.contracts.video_generation import VideoGenerationInput
from app.core.integrations.compshare.video import build_compshare_video_body
from app.core.integrations.compshare.video_capabilities import validate_h3_reference_material
from app.schemas.studio.shots import (
    ShotPromptAssetRef,
    ShotPromptCameraInfo,
    ShotVideoPromptPackRead,
)
from app.services.studio.generation.video.build_context import (
    REFERENCE_MODE,
    REQUIRED_FRAMES_BY_MODE,
    validate_images_count,
)
from app.services.film.shot_frame_prompt_tasks import resolve_frame_template_override


def _pack(**overrides: object) -> ShotVideoPromptPackRead:
    base: dict[str, object] = {
        "shot_id": "sd-1",
        "title": "落地窗前",
        "script_excerpt": "林晚站在公寓落地窗前，望着黄昏的城市天际线。",
        "action_beats": ["林晚走到落地窗前", "她停下脚步，视线落在远处的楼群上"],
        "characters": [
            ShotPromptAssetRef(
                type="character",
                name="林晚",
                description="22岁都市女性，黑色长直发及肩，米白色针织衫",
                file_id="file-char",
            ),
            ShotPromptAssetRef(type="character", name="苏陌", description="男同事"),
        ],
        "scene": ShotPromptAssetRef(
            type="scene",
            name="都市公寓客厅",
            description="落地窗与浅灰沙发",
            file_id="file-scene",
        ),
        "props": [ShotPromptAssetRef(type="prop", name="手机", description="黑色直板手机")],
        "camera": ShotPromptCameraInfo(
            camera_shot="MS", angle="EYE_LEVEL", movement="STATIC", duration=6
        ),
        "atmosphere": "安静、克制的黄昏氛围",
        "visual_style": "现实",
        "style": "真人都市",
        "negative_prompt": "不要新增无关人物",
    }
    base.update(overrides)
    return ShotVideoPromptPackRead(**base)


def _prose() -> H3Prose:
    return H3Prose(
        subject_definitions=(
            "<Subject 1>: 林晚, a 22-year-old urban woman with straight black shoulder-length "
            "hair and a cream knit sweater (source: <Picture 1>).\n"
            "<Subject 2>: the high-rise apartment living room with floor-to-ceiling windows at "
            "dusk (source: <Picture 2>)."
        ),
        summary=(
            "[reference generation] The target video shows the woman from <Subject 1> standing "
            "at the window of <Subject 2>."
        ),
        retention_analysis=(
            "<Subject 1> (appears in [Shot 1]): fully_preserved - her facial features and "
            "wardrobe are retained as referenced.\n"
            "<Subject 2> (appears in [Shot 1]): fully_preserved - the room layout and lighting "
            "direction are retained."
        ),
        detailed_description=(
            "The video keeps a restrained live-action look with soft dusk ambience.\n"
            "[Shot 1] A medium shot holds on <Subject 1> inside <Subject 2>. "
            "<Subject 1> (S1) says, <d>[Chinese] 你好，我叫林晚。</d>"
        ),
        overall_soundscape="Quiet indoor room tone with faint traffic through the glass.",
        non_diegetic_music="N/A",
    )


# --------------------------------------------------------------------------- #
# IR 构建
# --------------------------------------------------------------------------- #


def test_build_video_prompt_ir_assigns_token_order_and_stable_speakers() -> None:
    ir = build_video_prompt_ir(
        _pack(),
        dialogues=[IRDialogueInput(speaker_name="林晚", text="你好，我叫林晚。")],
    )

    # 参考顺序固定为 角色 → 场景 → 道具 → 服装，只收有参考图的资产。
    assert [ref.token for ref in ir.references] == ["图1", "图2"]
    assert [(ref.kind, ref.name) for ref in ir.references] == [
        ("character", "林晚"),
        ("scene", "都市公寓客厅"),
    ]

    labels = {subject.name: subject.label for subject in ir.subjects}
    assert labels["林晚"] == "Subject 1"
    assert labels["都市公寓客厅"] == "Subject 2"

    speaker = next(subject for subject in ir.subjects if subject.name == "林晚")
    assert speaker.speaker_id == "S1"
    assert ir.shots[0].dialogues[0].speaker_id == "S1"


def test_build_video_prompt_ir_excludes_assets_without_reference_image() -> None:
    ir = build_video_prompt_ir(_pack())

    # 手机 与 苏陌 都没有 file_id，不应占用参考 token。
    assert all(ref.name not in {"手机", "苏陌"} for ref in ir.references)
    assert any("参考图" in item for item in ir.warnings)


def test_build_video_prompt_ir_respects_reference_limit() -> None:
    ir = build_video_prompt_ir(
        _pack(
            # 角色卡需要剧本命中，这里让 12 个角色都真的出现在本镜头剧本里。
            script_excerpt="；".join(f"角色{i}走进画面" for i in range(12)),
            characters=[
                ShotPromptAssetRef(type="character", name=f"角色{i}", file_id=f"f{i}")
                for i in range(12)
            ],
            scene=None,
        ),
        max_references=9,
    )

    assert len(ir.references) == 9
    assert any("参考" in item for item in ir.warnings)


def test_character_card_requires_script_mention() -> None:
    """已关联但剧本里没出现的角色，不得占用参考 token。"""
    ir = build_video_prompt_ir(
        _pack(
            script_excerpt="空荡的走廊里只有风声。",
            action_beats=[],
            shot_description="无人空镜，镜头缓慢推近墙面的裂纹。",
            dialogue_summary="",
            characters=[
                ShotPromptAssetRef(type="character", name="林晚", file_id="file-char"),
            ],
            scene=None,
            props=[],
            costumes=[],
        )
    )

    assert ir.references == []
    assert any("林晚" in item and "没有出现" in item for item in ir.warnings)


def test_character_card_included_when_only_appearing_in_dialogue() -> None:
    """角色只靠台词出场时也要插卡（对白摘要里带说话人名）。"""
    ir = build_video_prompt_ir(
        _pack(
            script_excerpt="",
            action_beats=[],
            shot_description="",
            dialogue_summary="林晚：你到底还想骗我多久？",
            characters=[
                ShotPromptAssetRef(type="character", name="林晚", file_id="file-char"),
            ],
            scene=None,
            props=[],
            costumes=[],
        )
    )

    assert [(ref.kind, ref.name) for ref in ir.references] == [("character", "林晚")]


def test_character_card_included_when_mentioned_outside_script_excerpt() -> None:
    """命中来源不限于剧本摘录：标题、镜头描述、动作拍点都算。"""
    for field in ("title", "shot_description", "action_beats"):
        pack = _pack(
            script_excerpt="",
            action_beats=[],
            shot_description="",
            title="",
            dialogue_summary="",
            characters=[
                ShotPromptAssetRef(type="character", name="林晚", file_id="file-char"),
            ],
            scene=None,
            props=[],
            costumes=[],
        )
        if field == "action_beats":
            pack.action_beats = ["林晚推开门"]
        else:
            setattr(pack, field, "林晚站在窗前")

        ir = build_video_prompt_ir(pack)

        assert [ref.name for ref in ir.references] == ["林晚"], field


def test_scene_card_is_not_subject_to_script_mention() -> None:
    """场景/道具/服装不参与剧本命中判定，只按有无参考图决定。"""
    ir = build_video_prompt_ir(
        _pack(
            script_excerpt="什么都没有。",
            action_beats=[],
            shot_description="",
            characters=[],
            scene=ShotPromptAssetRef(type="scene", name="都市公寓客厅", file_id="file-scene"),
            props=[ShotPromptAssetRef(type="prop", name="手机", file_id="file-prop")],
            costumes=[],
        )
    )

    assert [(ref.kind, ref.name) for ref in ir.references] == [
        ("scene", "都市公寓客厅"),
        ("prop", "手机"),
    ]


# --------------------------------------------------------------------------- #
# H3 渲染
# --------------------------------------------------------------------------- #


def test_render_h3_reference_fallback_keeps_sections_ordered_and_hides_internal_tokens() -> None:
    ir = build_video_prompt_ir(_pack(), duration_seconds=6)
    result = render_h3_reference(ir, prose=None)

    positions = [result.text.index(f"{name}:") for name in REFERENCE_SECTION_ORDER]
    assert positions == sorted(positions)
    # 内部 token（图1）不能泄漏到 H3 输出，必须映射为 <Picture N>。
    assert "<Picture 1>" in result.text
    assert "图1" not in result.text
    assert result.warnings
    assert result.char_count > 0


def test_render_h3_reference_with_english_prose_is_structurally_clean() -> None:
    ir = build_video_prompt_ir(_pack(), duration_seconds=6)
    result = render_h3_reference(ir, prose=_prose())

    assert result.warnings == []
    assert "<Picture 1>" in result.text
    assert "图1" not in result.text


def test_render_h3_uses_base_sections_when_no_references() -> None:
    ir = build_video_prompt_ir(_pack(characters=[], scene=None, props=[], costumes=[]))
    result = render_h3(ir)

    positions = [result.text.index(f"{name}:") for name in BASE_SECTION_ORDER]
    assert positions == sorted(positions)
    assert "subject_definitions:" not in result.text


def test_validate_h3_reference_reports_missing_sections_and_shot1_timestamp() -> None:
    text = "\n\n".join(
        [
            "subject_definitions:\n<Subject 1>: a woman.",
            "summary:\n[reference generation] she stands still.",
            "detailed_description:\na restrained live-action look.\n"
            "[Shot 1] At 00:03.000, she stands still.",
        ]
    )

    warnings = validate_h3_reference(text)
    assert any("缺少 H3 必需段落" in item for item in warnings)
    assert any("不应带时间戳" in item for item in warnings)


def test_validate_h3_reference_flags_undefined_subject() -> None:
    text = "\n\n".join(
        [
            "subject_definitions:\n<Subject 1>: a woman.",
            "summary:\n[reference generation] this also uses <Subject 9>.",
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - kept.",
            "detailed_description:\na restrained live-action look.\n[Shot 1] she stands still.",
            "overall_soundscape:\nN/A",
            "non_diegetic_music:\nN/A",
        ]
    )

    warnings = validate_h3_reference(text)
    assert any("<Subject 9>" in item for item in warnings)


def test_validate_h3_reference_requires_style_sentence_before_first_shot() -> None:
    text = "\n\n".join(
        [
            "subject_definitions:\n<Subject 1>: a woman.",
            "summary:\n[reference generation] she stands still.",
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - kept.",
            "detailed_description:\n[Shot 1] she stands still.",
            "overall_soundscape:\nN/A",
            "non_diegetic_music:\nN/A",
        ]
    )

    warnings = validate_h3_reference(text)
    assert any("确立风格" in item for item in warnings)


def test_validate_h3_reference_flags_unpaired_dialogue_tags() -> None:
    text = "\n\n".join(
        [
            "subject_definitions:\n<Subject 1>: a woman.",
            "summary:\n[reference generation] she speaks.",
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - kept.",
            "detailed_description:\na look.\n[Shot 1] <d>[Chinese] 你好。",
            "overall_soundscape:\nN/A",
            "non_diegetic_music:\nN/A",
        ]
    )

    warnings = validate_h3_reference(text)
    assert any("<d> 台词标签未成对闭合" in item for item in warnings)


# --------------------------------------------------------------------------- #
# 短剧规则常量层（D2）
# --------------------------------------------------------------------------- #


def test_short_drama_rules_expose_vertical_and_reference_constants() -> None:
    assert rules.REFERENCE_TOKEN_PREFIX == "图"
    # 与 H3 参考图片上限一致。
    assert rules.MAX_REFERENCE_IMAGES == 9
    assert rules.VERTICAL_FRAME_RULES
    assert 0.0 < rules.SUBTITLE_SAFE_AREA_RATIO < 0.5


def test_short_drama_rules_quantify_action_density_and_micro_expressions() -> None:
    assert rules.action_beats_for_duration(2) == 1
    assert rules.action_beats_for_duration(5) == 2
    assert rules.action_beats_for_duration(10) == 3
    assert rules.micro_expression_quota(10) == (0, 2)
    assert rules.micro_expression_quota(20) == (2, 3)


def test_short_drama_rules_estimate_dialogue_seconds_by_tone() -> None:
    text = "他凭什么这样说，我不同意！"

    heated = rules.estimate_dialogue_seconds(text, rate="heated")
    normal = rules.estimate_dialogue_seconds(text, rate="normal")
    tender = rules.estimate_dialogue_seconds(text, rate="tender")

    assert heated < normal < tender

    longer = rules.estimate_dialogue_seconds(text * 4, rate="normal")
    assert longer > normal


def test_short_drama_rules_find_banned_abstract_words() -> None:
    assert rules.find_abstract_words("画面唯美，很有电影感") == ["唯美", "电影感"]
    assert rules.find_abstract_words("她在窗前停下脚步") == []


# --------------------------------------------------------------------------- #
# 参考图模式（参考图模式与首尾帧互斥，图片顺序即 <Picture N> 编号顺序）
# --------------------------------------------------------------------------- #


def test_reference_mode_uses_no_shot_frames() -> None:
    assert REQUIRED_FRAMES_BY_MODE[REFERENCE_MODE] == ()


def test_validate_images_count_bounds_for_reference_mode() -> None:
    with pytest.raises(HTTPException) as empty_exc:
        validate_images_count(REFERENCE_MODE, [])
    assert empty_exc.value.status_code == 400
    # 缺图必须给出可执行的下一步，而不是只报数字。
    assert "text_only" in empty_exc.value.detail

    validate_images_count(REFERENCE_MODE, ["file-1"])
    validate_images_count(REFERENCE_MODE, [f"file-{i}" for i in range(9)])

    with pytest.raises(HTTPException) as over_exc:
        validate_images_count(REFERENCE_MODE, [f"file-{i}" for i in range(10)])
    assert over_exc.value.status_code == 400
    assert "9" in over_exc.value.detail and "10" in over_exc.value.detail


def test_validate_images_count_for_frame_mode_is_still_exact() -> None:
    validate_images_count("first", ["file-1"])
    with pytest.raises(HTTPException):
        validate_images_count("first", [])
    with pytest.raises(HTTPException):
        validate_images_count("first_last", ["file-1"])


def test_h3_reference_material_rejects_frames_mixed_with_references() -> None:
    with pytest.raises(ValueError) as exc:
        validate_h3_reference_material(
            VideoGenerationInput(
                prompt="x",
                model="MiniMax-H3",
                ratio="9:16",
                reference_images=["data:image/png;base64,AAA"],
                first_frame_base64="data:image/png;base64,BBB",
            )
        )
    assert "首尾帧素材不能与参考图片" in str(exc.value)


def test_h3_reference_material_enforces_image_cap_and_prompt_length() -> None:
    with pytest.raises(ValueError) as cap_exc:
        validate_h3_reference_material(
            VideoGenerationInput(
                prompt="x",
                model="MiniMax-H3",
                ratio="9:16",
                reference_images=[f"data:image/png;base64,{i}" for i in range(10)],
            )
        )
    assert "最多 9 张" in str(cap_exc.value)

    with pytest.raises(ValueError) as len_exc:
        validate_h3_reference_material(
            VideoGenerationInput(prompt="x" * 7001, model="MiniMax-H3", ratio="9:16")
        )
    assert "最多 7000 字符" in str(len_exc.value)

    # 边界值放行。
    validate_h3_reference_material(
        VideoGenerationInput(prompt="x" * 7000, model="MiniMax-H3", ratio="9:16")
    )


def test_build_compshare_video_body_emits_ordered_reference_images() -> None:
    body = build_compshare_video_body(
        VideoGenerationInput(
            prompt="[Shot 1] hold on <Subject 1>",
            model="MiniMax-H3",
            ratio="9:16",
            seconds=5,
            reference_images=[
                "data:image/png;base64,AAA",
                "data:image/png;base64,BBB",
            ],
        )
    )
    roles = [item.get("role") for item in body["content"]]
    assert roles == [None, "reference_image", "reference_image"]
    urls = [item["image_url"]["url"] for item in body["content"][1:]]
    assert urls[0].endswith("AAA")
    assert urls[1].endswith("BBB")
    assert body["ratio"] == "9:16"
    assert body["duration"] == 5


def test_build_compshare_video_body_keeps_frame_mode_untouched() -> None:
    body = build_compshare_video_body(
        VideoGenerationInput(
            prompt="x",
            model="MiniMax-H3",
            ratio="16:9",
            first_frame_base64="data:image/png;base64,CCC",
            last_frame_base64="data:image/png;base64,DDD",
        )
    )
    roles = [item.get("role") for item in body["content"]]
    assert roles == [None, "first_frame", "last_frame"]


# --------------------------------------------------------------------------- #
# A5：平台自带提示词优化作为可选开关，默认关闭
# --------------------------------------------------------------------------- #


def test_platform_prompt_optimization_is_opt_in() -> None:
    base = {
        "prompt": "x",
        "model": "MiniMax-H3",
        "ratio": "9:16",
        "reference_images": ["data:image/png;base64,AAA"],
    }

    default_body = build_compshare_video_body(VideoGenerationInput(**base))
    assert "use_context_ir" not in default_body
    assert "skill_id" not in default_body

    enabled_body = build_compshare_video_body(
        VideoGenerationInput(**base, use_context_ir=True, skill_id="h3-skill")
    )
    assert enabled_body["use_context_ir"] is True
    assert enabled_body["skill_id"] == "h3-skill"

    # 未开启优化时，即便传了 skill_id 也不下发（避免歧义）。
    no_skill_body = build_compshare_video_body(
        VideoGenerationInput(**base, use_context_ir=True)
    )
    assert no_skill_body["use_context_ir"] is True
    assert "skill_id" not in no_skill_body


# --------------------------------------------------------------------------- #
# B1：帧提示词模板开放到后台可编辑
# --------------------------------------------------------------------------- #


class _FakeTemplate:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeScalars:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def first(self) -> object | None:
        return self._row


class _FakeExecuteResult:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._row)


class _FakeTemplateDB:
    def __init__(self, row: object | None = None) -> None:
        self._row = row

    async def execute(self, stmt: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(self._row)


def test_build_frame_prompt_template_falls_back_to_builtin() -> None:
    for frame_type, name in (("first", "首帧"), ("last", "尾帧"), ("key", "关键帧")):
        template = build_frame_prompt_template(frame_type)
        assert name in template.template
        assert set(template.input_variables).issubset(set(_SHOT_FRAME_INPUT_VARS))


def test_build_frame_prompt_template_uses_backend_override() -> None:
    template = build_frame_prompt_template("first", override="自定义模板 {title} / {script_excerpt}")
    assert "自定义模板" in template.template
    assert set(template.input_variables).issubset(set(_SHOT_FRAME_INPUT_VARS))


def test_build_frame_prompt_template_falls_back_on_invalid_override() -> None:
    # 变量名不在允许集合里 -> 回退内置，不抛异常
    template = build_frame_prompt_template("key", override="{not_an_allowed_variable}")
    assert "关键帧" in template.template


def test_frame_agents_accept_backend_template_override() -> None:
    llm = object()
    first = ShotFirstFramePromptAgent(llm, frame_template="后台首帧模板 {title}")
    assert "后台首帧模板" in first.prompt_template.template
    # 未注入时仍用内置
    assert "首帧" in ShotFirstFramePromptAgent(llm).prompt_template.template
    assert "尾帧" in ShotLastFramePromptAgent(llm).prompt_template.template
    assert "关键帧" in ShotKeyFramePromptAgent(llm).prompt_template.template


def test_resolve_frame_template_override_reads_backend_row() -> None:
    assert asyncio.run(resolve_frame_template_override(_FakeTemplateDB(None), frame_type="first")) is None
    assert (
        asyncio.run(resolve_frame_template_override(_FakeTemplateDB(_FakeTemplate("  ")), frame_type="first"))
        is None
    )
    assert (
        asyncio.run(
            resolve_frame_template_override(_FakeTemplateDB(_FakeTemplate("后台模板 {title}")), frame_type="last")
        )
        == "后台模板 {title}"
    )
    # 未知 frame_type 直接返回 None（不查库）
    assert asyncio.run(resolve_frame_template_override(_FakeTemplateDB(_FakeTemplate("x")), frame_type="bogus")) is None
