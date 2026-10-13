"""项目级风格包（C2）。

目的：把「画面表现形式 × 题材风格」翻译成一组图像模型真正吃得进去的摄影质感词，
一处配置、全局注入到资产图 / 角色卡 / 分镜帧的提示词里。

字段语义（`backend/app/models/types.py`）：
- `ProjectVisualStyle` = `visual_style` 字段：`现实` / `动漫`（决定实拍质感还是绘本质感）
- `ProjectStyle` = `style` 字段：`真人都市` / `真人科幻` / `真人古装` /
  `动漫科幻` / `动漫3D` / `国漫` / `水墨画`（决定具体题材的调色与光影倾向）

设计取舍：
- 只写**画面可观察**的要素（光线、材质、景深、色调、构图倾向），不写抽象评价词；
- 不写「8K 分辨率」「f/1.4 大光圈」这类我们实际不用的档位描述
  （出图统一 1K，且 gpt-image-2.5 / PIX 对光圈数值不敏感）；
- 未登记的风格组合回落到通用写实包，保证永远有值。
"""

from __future__ import annotations

# 表现形式层（visual_style：现实 / 动漫）
FORMAT_PACKS: dict[str, str] = {
    "现实": "实拍电影质感，真实皮肤纹理与毛孔细节，自然光照逻辑，物理正确的材质反射，轻微胶片颗粒",
    "动漫": "日式动画赛璐璐上色，干净线稿与清晰描边，色块分区明确，柔和渐变阴影，无真实皮肤纹理",
}

# 题材风格层（style：真人都市 / … / 水墨画）
STYLE_PACKS: dict[str, str] = {
    "真人都市": "现代都市实拍，冷暖对比色调，窗光与霓虹混合光源，浅景深虚化都市背景，画面干净通透",
    "真人科幻": "近未来实拍，冷蓝青色基调，硬光源与体积光，金属与玻璃材质反光明确，低饱和高对比",
    "真人古装": "古装实拍，暖黄烛光与自然天光，柔和高光，丝绸与刺绣材质层次分明，画面留白克制",
    "动漫科幻": "科幻动画，高饱和冷暖撞色，发光边缘与粒子特效，机械硬边线与高光反射块面清晰",
    "动漫3D": "三维渲染动画，皮肤与布料次表面散射，柔顺的全局光照，圆润造型，边缘抗锯齿干净",
    "国漫": "国风动画，低饱和水墨感配色，衣纹线条流畅有笔锋，画面层次靠色阶而非写实光影",
    "水墨画": "水墨渲染，宣纸质地与墨色浓淡晕染，留白为主，笔触边缘自然飞白，避免写实高光",
}

DEFAULT_STYLE_PACK = STYLE_PACKS["真人都市"]
DEFAULT_FORMAT_PACK = FORMAT_PACKS["现实"]

# 判定用集合
_ANIME_FORMATS = {"动漫"}
_ANIME_STYLES = {"动漫科幻", "动漫3D", "国漫", "水墨画"}
_ANCIENT_STYLES = {"真人古装"}


def _enum_text(value: object) -> str:
    """枚举成员或普通字符串统一取文本值（ORM 取出的是 str，枚举取出的是成员）。"""
    from enum import Enum

    if isinstance(value, Enum):
        return str(value.value or "")
    return str(getattr(value, "value", value) or "")


def format_pack_for(visual_style: object) -> str:
    """表现形式包：现实 / 动漫（入参是 `visual_style` 字段）。"""
    return FORMAT_PACKS.get(_enum_text(visual_style), DEFAULT_FORMAT_PACK)


def motif_pack_for(style: object) -> str:
    """题材风格包：真人都市 / 真人科幻 / … / 水墨画（入参是 `style` 字段）。"""
    return STYLE_PACKS.get(_enum_text(style), DEFAULT_STYLE_PACK)


def style_pack_line(*, visual_style: object = "", style: object = "") -> str:
    """拼成可直接插进提示词的「风格与质感」段。永远返回非空字符串。"""
    parts = [motif_pack_for(style), format_pack_for(visual_style)]
    seen: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "；".join(seen)


# 统一负面词表（C1）：所有图片模板共用同一份，避免各模板各写一套。
# 注意：图片链路没有独立的 negative 参数，负面词直接写进提示词正文。
COMMON_NEGATIVE_IMAGE = (
    "low quality, worst quality, blurry, out of focus, deformed, bad anatomy, "
    "bad hands, extra fingers, missing fingers, extra limbs, bad proportions, "
    "watermark, text, logo, signature, overexposed, underexposed, "
    "plastic skin, wax figure, doll, lowres, jpeg artifacts, grainy"
)

REALISTIC_NEGATIVE_IMAGE = "cartoon, 3d render, cgi, illustration, painting, sketch, anime"
ANIME_NEGATIVE_IMAGE = "bad anime, deformed anime, flat color, flat shading, 3d render, cgi, photorealistic"
ANCIENT_NEGATIVE_IMAGE = "modern clothing, modern background, contemporary elements"


def is_anime(*, visual_style: object = "", style: object = "") -> bool:
    visual_text = _enum_text(visual_style)
    style_text = _enum_text(style)
    if visual_text in _ANIME_FORMATS or style_text in _ANIME_STYLES:
        return True
    return "anime" in visual_text.lower()


def negative_image_prompt(*, visual_style: object = "", style: object = "") -> str:
    """按表现形式/题材风格挑负面词。"""
    lines = [COMMON_NEGATIVE_IMAGE]
    lines.append(
        ANIME_NEGATIVE_IMAGE if is_anime(visual_style=visual_style, style=style) else REALISTIC_NEGATIVE_IMAGE
    )
    if _enum_text(style) in _ANCIENT_STYLES:
        lines.append(ANCIENT_NEGATIVE_IMAGE)
    return "，".join(lines)


__all__ = [
    "FORMAT_PACKS",
    "STYLE_PACKS",
    "DEFAULT_STYLE_PACK",
    "DEFAULT_FORMAT_PACK",
    "COMMON_NEGATIVE_IMAGE",
    "REALISTIC_NEGATIVE_IMAGE",
    "ANIME_NEGATIVE_IMAGE",
    "ANCIENT_NEGATIVE_IMAGE",
    "format_pack_for",
    "motif_pack_for",
    "style_pack_line",
    "is_anime",
    "negative_image_prompt",
]
