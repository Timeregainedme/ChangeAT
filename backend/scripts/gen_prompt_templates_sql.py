"""生成 `backend/sql/012-rewrite-prompt-templates.sql`（C1 + C2 + B1）。

为什么要生成而不是手写：
- 帧提示词模板（B1）的权威文本在 `app/chains/agents/shot_frame_prompt_agents.py` 里，
  手抄一份进 SQL 必然漂移；这里直接 import 常量，保证 SQL 与代码逐字一致。
- 资产模板（C1）改成统一的新文案与统一负面词槽位，版本化在 SQL 里便于回溯。
- 视频提示词（video_prompt）**故意不播种**：A1 决定视频提示词由 IR → H3 渲染器生成，
  一旦数据库存在 video_prompt 模板就会走模板分支把 IR 链路绕过去。

用法：cd backend && .venv/bin/python scripts/gen_prompt_templates_sql.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.chains.agents.shot_frame_prompt_agents import (  # noqa: E402
    _KEY_FRAME_TEMPLATE,
    _LAST_FRAME_TEMPLATE,
    _FIRST_FRAME_TEMPLATE,
    _SHOT_FRAME_INPUT_VARS,
)

# 资产模板通用变量（与 build_prompt_with_template 传入的 variables 对齐）
ASSET_VARS = [
    "name",
    "description",
    "tags",
    "visual_style",
    "style",
    "view_angle",
    "quality_level",
    "format",
    "style_pack",
    "negative_prompt",
]

NEGATIVE_BLOCK = """
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}"""

ASSET_TEMPLATES: dict[str, tuple[str, str, list[str], str]] = {
    "actor_image_front": (
        "演员正面图片提示词",
        "演员正面定妆照",
        ASSET_VARS,
        """{{ style_pack }}

电影级演员定妆照，正面平视半身，纯色中性背景，脚下有自然接触阴影：
{{ description }}

画面要求：
- 正面平视机位，双眼直视镜头，肩线水平，构图居中偏上
- 面部细节清晰可辨：眼型、眉形、鼻梁、唇形、下颌线与发际线交代明确
- 柔和均匀的主光加一侧补光，面部无硬阴影、无油光、无过曝
- 服装平整，发型完整，不出现手持道具
- 写实皮肤质感，保留真实毛孔与细纹，不做磨皮
- 画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "actor_image_other": (
        "演员侧面/后面图片提示词",
        "演员非正面视角",
        ASSET_VARS,
        """{{ style_pack }}

与正面定妆照完全同一个人，身份严格一致：相同脸型、五官比例、发型、发色、肤色与年龄：
{{ description }}

视角完全切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不得残留任何正面元素（不出现正脸、不出现双眼直视镜头）
- 头部、颈部与肩部的朝向符合该视角，透视与轮廓正确，无面部扭曲
- 站位、景别、光线与背景承接正面定妆照，人物比例一致
- 不出现手持道具，画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "character_image_front": (
        "角色正面图片提示词",
        "角色正面定妆照（身份锁定）",
        ASSET_VARS,
        """{{ style_pack }}

角色定妆照，正面平视半身，纯色中性背景，脚下有自然接触阴影。

身份参考（严格锁定，不得改动）：
- 若提供了参考图，参考图中的人物即为本角色「{{ name }}」的身份基准
- 参考图只约束长相、发型、发色、肤色、体型与年龄，不得换脸、不得改变发型发色与年龄感
- 若参考图包含服装，则沿用该服装，服装颜色与款式不得改变
{{ description }}

画面要求：
- 正面平视机位，双眼直视镜头，肩线水平，构图居中偏上
- 柔和均匀的主光加一侧补光，面部无硬阴影、无油光、无过曝
- 写实皮肤质感，保留真实毛孔与细纹，不做磨皮
- 不出现手持道具，画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "character_image_other": (
        "角色侧面/后面图片提示词",
        "角色非正面视角（身份锁定）",
        ASSET_VARS,
        """{{ style_pack }}

与角色正面定妆照完全同一个人，身份严格一致：相同脸型、五官比例、发型、发色、肤色、年龄与服装。

视角完全切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不得残留任何正面元素（不出现正脸、不出现双眼直视镜头）
- 头部、颈部与肩部的朝向符合该视角，透视与轮廓正确，无面部扭曲
- 站位、景别、光线与背景承接正面定妆照，人物比例一致
- 不出现手持道具，画面内不出现文字、标识与水印
{{ description }}""" + NEGATIVE_BLOCK,
    ),
    "prop_image_front": (
        "道具图片提示词",
        "高质量道具特写",
        ASSET_VARS,
        """{{ style_pack }}

道具特写，主体居中，简洁环境背景：
{{ description }}

画面要求：
- 镜头方向：正面；道具完整入画，不被裁切，不出现手持痕迹
- 材质交代明确：金属反光、皮革纹理、玻璃折射、布料纤维与磨损细节可见
- 柔和的侧上方主光，轮廓光勾边，主体与背景分离清楚
- 除道具本身外不加多余元素，画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "prop_image_other": (
        "道具侧面/后面图片提示词",
        "道具非正面视角",
        ASSET_VARS,
        """{{ style_pack }}

与正面图完全同一个道具，形制、颜色、材质与磨损状态严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不残留正面特征
- 透视正确，结构关系合理，比例与正面图一致
- 光线与背景承接正面图，材质表现保持一致
- 不出现手持痕迹，画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "scene_image_front": (
        "场景图片提示词",
        "高质量电影场景",
        ASSET_VARS,
        """{{ style_pack }}

电影级场景定景画面，竖屏构图，空间层次清楚：
{{ description }}

画面要求：
- 镜头方向：正面；画面正中为场景主体区域，前中后景分明
- 光源方向明确，环境氛围自然（雾、雨丝、光斑、尘埃等按需出现）
- 空间尺度合理，建筑与陈设结构正确，透视不畸变
- 为演员留出可站立的表演空间，地面与墙面材质细节清楚
- 画面内不出现文字、标识与水印，不出现人物正脸特写""" + NEGATIVE_BLOCK,
    ),
    "scene_image_other": (
        "场景侧面/后面图片提示词",
        "同一场景的其他机位",
        ASSET_VARS,
        """{{ style_pack }}

与正面定景画面完全同一场景，空间结构、陈设与光线条件严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 同一空间内的另一个机位，墙、地面、门窗与陈设的相对位置必须自洽
- 不出现与正面图矛盾的结构，不新增主要陈设
- 光线方向相对场景保持一致，色温与氛围延续
- 画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "costume_image_front": (
        "服装图片提示词",
        "高质量服装呈现",
        ASSET_VARS,
        """{{ style_pack }}

服装整体呈现，完整全身穿着，简洁中性背景：
{{ description }}

画面要求：
- 服装为画面主体，占画面三分之二以上，版型与剪裁交代清楚
- 布料纹理、车线、钮扣、拉链、金属配件与褶皱细节清晰可见
- 柔和的正面主光加侧向补光，服装颜色还原准确，无偏色
- 画面内不出现文字、标识与水印，不出现人物面部特写分散注意力""" + NEGATIVE_BLOCK,
    ),
    "costume_image_other": (
        "服装侧面/后面图片提示词",
        "同一套服装的其他视角",
        ASSET_VARS,
        """{{ style_pack }}

与正面服装图完全同一套服装，版型、颜色、材质与细节严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不残留正面特征
- 同一件衣服的侧面/背面结构合理，接缝、开衩与配饰位置自洽
- 光线与背景承接正面图，布料质感与颜色保持一致
- 画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
    "combined": (
        "通用兜底图片提示词",
        "无专用类别时的通用画面模板",
        ASSET_VARS,
        """{{ style_pack }}

高质量{{ visual_style }}画面主体：
{{ description }}

画面要求：
- 主体明确、构图稳定，主体占画面主要面积
- 光线方向明确，材质与纹理表现到位
- 画面内不出现文字、标识与水印""" + NEGATIVE_BLOCK,
    ),
}

FRAME_TEMPLATES: dict[str, tuple[str, str, list[str], str]] = {
    "frame_head_prompt": (
        "镜头首帧提示词模板",
        "分镜首帧基础提示词（后台可编辑）",
        list(_SHOT_FRAME_INPUT_VARS),
        _FIRST_FRAME_TEMPLATE,
    ),
    "frame_tail_prompt": (
        "镜头尾帧提示词模板",
        "分镜尾帧基础提示词（后台可编辑）",
        list(_SHOT_FRAME_INPUT_VARS),
        _LAST_FRAME_TEMPLATE,
    ),
    "frame_key_prompt": (
        "镜头关键帧提示词模板",
        "分镜关键帧基础提示词（后台可编辑）",
        list(_SHOT_FRAME_INPUT_VARS),
        _KEY_FRAME_TEMPLATE,
    ),
}

ALL_TEMPLATES = {**ASSET_TEMPLATES, **FRAME_TEMPLATES}


def sql_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def build_sql() -> str:
    lines: list[str] = [
        "-- 012-rewrite-prompt-templates.sql",
        "-- 提示词改造第 2 档：C0/C1/C2 资产模板整改 + B1 帧模板入 DB。",
        "-- 由 backend/scripts/gen_prompt_templates_sql.py 生成，请勿手工编辑。",
        "-- 幂等：已存在同类别则 UPDATE，不存在则 INSERT。",
        "-- 注意：video_prompt 故意不播种 —— 视频提示词走 IR → H3 渲染器（A1）。",
        "",
        "SET NAMES utf8mb4;",
        "",
    ]
    for category, (name, preview, variables, content) in ALL_TEMPLATES.items():
        lines.append(f"-- ===== {category} =====")
        lines.append(
            "UPDATE `prompt_templates` SET "
            f"`name` = {sql_literal(name)}, "
            f"`preview` = {sql_literal(preview)}, "
            f"`content` = {sql_literal(content)}, "
            f"`variables` = CAST({sql_literal(json.dumps(variables, ensure_ascii=False))} AS JSON), "
            "`is_default` = 1, `is_system` = 1, "
            "`updated_at` = NOW() "
            f"WHERE `category` = {sql_literal(category)};"
        )
        lines.append(
            "INSERT INTO `prompt_templates` "
            "(`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) "
            f"SELECT UUID(), {sql_literal(category)}, {sql_literal(name)}, {sql_literal(preview)}, "
            f"{sql_literal(content)}, CAST({sql_literal(json.dumps(variables, ensure_ascii=False))} AS JSON), 1, 1, NOW(), NOW() "
            f"FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = {sql_literal(category)});"
        )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    out = BACKEND_DIR / "sql" / "012-rewrite-prompt-templates.sql"
    out.write_text(build_sql(), encoding="utf-8")
    print(f"wrote {out} ({len(ALL_TEMPLATES)} categories)")


if __name__ == "__main__":
    main()
