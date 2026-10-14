"""PromptCategory 枚举接口测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.v1.routes.studio.prompts import _PROMPT_CATEGORY_ZH
from app.models.studio import PromptCategory


def test_list_prompt_categories_returns_value_label_description(client: TestClient) -> None:
    response = client.get("/api/v1/studio/prompts/categories")
    assert response.status_code == 200

    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "success"

    items = body["data"]
    assert isinstance(items, list)

    values = {item["value"] for item in items}
    labels = {item["label"] for item in items}
    descriptions = {item["description"] for item in items}

    assert values == {
        "frame_head_image",
        "frame_tail_image",
        "frame_key_image",
        "frame_head_prompt",
        "frame_tail_prompt",
        "frame_key_prompt",
        "video_prompt",
        "storyboard_prompt",
        "bgm",
        "sfx",
        "character_image_front",
        "character_image_other",
        "actor_image_front",
        "actor_image_other",
        "prop_image_front",
        "prop_image_other",
        "scene_image_front",
        "scene_image_other",
        "costume_image_front",
        "costume_image_other",
        "combined",
        "agent_script_division",
        "agent_element_extract",
        "agent_character_portrait",
        "agent_scene_info",
        "agent_prop_info",
        "agent_costume_info",
        "agent_consistency_check",
        "agent_entity_merge",
        "agent_script_optimize",
        "agent_script_simplify",
        "agent_variant_analyze",
        "agent_h3_video",
    }
    assert "首帧图片" in labels
    assert "关键帧图片" in labels
    assert "用于生成首帧图片的提示词" in descriptions
    assert "分镜拆解提示词" in labels
    assert "H3 视频提示词" in labels
    assert "剧本分镜 Agent 的系统提示词" in descriptions


def test_prompt_category_mapping_is_complete() -> None:
    assert set(_PROMPT_CATEGORY_ZH.keys()) == set(PromptCategory)


