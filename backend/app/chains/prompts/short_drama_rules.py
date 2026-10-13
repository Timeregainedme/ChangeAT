"""短剧（竖屏 / 红果向）提示词规则常量层。

本模块把「红果短剧」这一内容形态的创作纪律沉淀为可复用常量与纯函数，
供分镜帧提示词、图片提示词与视频提示词三条链路共同注入。

边界声明（重要）：

- 本模块只提供创作参考与结构化约束，**不代表任何平台的官方规则，也不构成效果保证**。
- 量化数值来自公开短剧创作方法论，用于排期与长度校验，不应作为平台硬性上限对外宣传。
- 不写「4K/8K 分辨率」这类与真实输出档位无关的措辞：文字的清晰度不等于实际输出尺寸。
"""

from __future__ import annotations

import math
from typing import Iterable

# --------------------------------------------------------------------------- #
# 1. 竖屏构图
# --------------------------------------------------------------------------- #

VERTICAL_FRAME_RULES: tuple[str, ...] = (
    "竖屏优先：主体置于画面上中部，人物头顶留出少量空间且不被裁切",
    "画面下部预留字幕安全区，不把关键信息、手部动作或道具细节放在该区域内",
    "以特写、近景、中景为主，避免横向大调度、多人横向并排与宽幅大全景",
    "优先竖向纵深分层（前/中/后景清楚），弱化左右方向的横向展开",
    "避免本镜头内出现横向快速横摇；需要运动时改用竖向推拉或小幅跟随",
)

SUBTITLE_SAFE_AREA_RATIO = 0.15
SUBTITLE_SAFE_AREA_RULE = "画面下部约 15% 设为字幕安全区，保持干净的纯色或虚化表面，不承载剧情信息"


# --------------------------------------------------------------------------- #
# 2. 情绪 = 行为（不写情绪标签，写可见行为）
# --------------------------------------------------------------------------- #

EMOTION_AS_BEHAVIOR_RULES: tuple[str, ...] = (
    "不写「他很生气」「她很难过」这类情绪标签，改写为可见的身体行为",
    "情绪必须落到具体动作、手部、呼吸、下颌或视线变化上，让观众自己读出来",
    "每个微表情都要有触发原因（看到了什么/听到了什么）与持续时长",
    "不要用抽象形容词代替表演设计（如「演技炸裂」「情绪饱满」）",
)

EMOTION_AS_BEHAVIOR_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("他很难过", "他原本正在举杯，动作停约 0.4 秒，随后把杯子放回桌面"),
    ("她非常生气", "她指尖收紧攥住纸巾，指节发白，视线抬到对方脸上不再移开"),
    ("他有点心虚", "他视线向右下偏移约 0.3 秒，随后把双手插进外套口袋"),
    ("她很震惊", "她手里的文件滑落到膝盖上，嘴唇张开约半秒没有合上"),
)

# 表演通道适配：按画面里实际能看到的身体部位选择表演着力点。
PERFORMANCE_CHANNEL_RULES: tuple[tuple[str, str], ...] = (
    ("脸部可见", "用眼神方向、眼睑开合与面部极小变化承载情绪"),
    ("只露手部", "用握力变化、动作节拍与对物体的触碰力度承载情绪"),
    ("背影或侧后", "用重心转移、肩颈线条与呼吸起伏承载情绪"),
    ("只露脚部", "用步态节奏、停顿与重量转移承载情绪"),
    ("全身远景", "用整体姿态、空间占据与朝向变化承载情绪"),
)


def micro_expression_quota(duration_seconds: float) -> tuple[int, int]:
    """返回该时长下单个角色微表情的事件数区间（下限, 上限）。

    0 个微表情是完全允许的：并非每个镜头都需要微表情。
    """
    seconds = max(0.0, float(duration_seconds or 0.0))
    if seconds <= 15.0:
        return (0, 2)
    if seconds <= 30.0:
        return (2, 3)
    return (2, 3)


# --------------------------------------------------------------------------- #
# 3. 单集节奏与钩子 / 卡点
# --------------------------------------------------------------------------- #

# 参考口径：约 150 字/分钟。
CHARS_PER_MINUTE = 150
SHORT_SENTENCE_CHARS = 20
MAX_SINGLE_UTTERANCE_CHARS = 50
COMPACT_EPISODE_CHARS = 1000

# 3 秒情绪入口 / 15 秒出现变化 / 45 秒形成强期待。
EMOTION_ENTRY_SECONDS = 3.0
CHANGE_SECONDS = 15.0
STRONG_EXPECTATION_SECONDS = 45.0

# 付费卡点大致落在单集时长的这些比例位置。
PAYWALL_BEAT_RATIOS: tuple[float, ...] = (0.10, 0.30, 0.50, 0.70, 0.90)

PACING_RULES: tuple[str, ...] = (
    f"开场约 {EMOTION_ENTRY_SECONDS:.0f} 秒内进入情绪或冲突，不要铺垫环境空镜",
    f"约 {CHANGE_SECONDS:.0f} 秒内必须出现一次信息或关系的变化",
    f"约 {STRONG_EXPECTATION_SECONDS:.0f} 秒内形成一次强期待（悬念、反转或爽点）",
    f"单次发言不超过约 {MAX_SINGLE_UTTERANCE_CHARS} 字，超长台词在语义停顿处拆镜",
    f"单句以短句为主（约 {SHORT_SENTENCE_CHARS} 字以内），避免长定语从句",
)

# 情绪配比参考（按题材）。数值为百分比参考，不是硬性配额。
EMOTION_MIX_BY_GENRE: dict[str, tuple[tuple[str, int], ...]] = {
    "甜宠": (("甜", 60), ("微虐", 30), ("惊喜", 10)),
    "复仇": (("压抑", 40), ("爽", 50), ("解气", 10)),
    "重生": (("爽", 50), ("期待", 30), ("温暖", 20)),
    "家庭": (("共情", 40), ("委屈", 30), ("和解", 30)),
}

# 商业爽感链路：每一轮爽点都应走完这四步，避免只给结果不给过程。
SATISFACTION_CHAIN: tuple[str, ...] = ("受压或误判", "主动反击", "他人态度变化", "实际收获")

BEAT_TYPE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("爆点", "意外改变观众认知的信息"),
    ("虐点", "重要关系或目标遭受损失"),
    ("爽点", "长期积累后的能力、秩序或归属被兑现"),
)


# --------------------------------------------------------------------------- #
# 4. 语速 / 时长 / 动作密度
# --------------------------------------------------------------------------- #

# 参考语速（字/秒）。
SPEECH_RATE_BY_TONE: dict[str, float] = {
    "heated": 4.0,  # 急促争执
    "normal": 3.0,  # 正常陈述
    "tender": 2.0,  # 深情、悲伤、沉思
    "whisper": 2.0,  # 低语、虚弱
}

DEFAULT_SPEECH_RATE = SPEECH_RATE_BY_TONE["normal"]
DEFAULT_PAUSE_SECONDS = 0.4
DEFAULT_HEAD_TAIL_MARGIN_SECONDS = 1.0

_PAUSE_MARKS = "，。！？；：、…,.!?;:"

TIMING_RULES: tuple[str, ...] = (
    "最小规划时长 = 台词字数 ÷ 语速（向上取整） + 标点停顿 + 首尾安全余量",
    "每处标点停顿按 0.3–0.5 秒估算，镜头首尾各留约 0.5 秒避免切掉台词",
    "超长连续台词优先在语义停顿处拆成多镜，而不是压缩语速",
)


def _count_spoken_chars(text: str) -> int:
    """统计可计入语速的字数：去掉空白与标点。"""
    return sum(1 for char in str(text or "") if not char.isspace() and char not in _PAUSE_MARKS)


def _count_pauses(text: str) -> int:
    return sum(1 for char in str(text or "") if char in _PAUSE_MARKS)


def estimate_dialogue_seconds(
    text: str,
    *,
    rate: str | float = "normal",
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    head_tail_margin: float = DEFAULT_HEAD_TAIL_MARGIN_SECONDS,
) -> float:
    """估算一句台词所需的最小时长（秒）。

    `rate` 可以是 `SPEECH_RATE_BY_TONE` 的键，也可以直接给「字/秒」数值。
    未知语速键回落到正常陈述语速。
    """
    if isinstance(rate, str):
        speed = SPEECH_RATE_BY_TONE.get(rate, DEFAULT_SPEECH_RATE)
    else:
        speed = float(rate)
    if speed <= 0:
        speed = DEFAULT_SPEECH_RATE

    chars = _count_spoken_chars(text)
    if chars == 0:
        return 0.0
    speaking = math.ceil(chars / speed)
    return round(speaking + _count_pauses(text) * max(0.0, pause_seconds) + max(0.0, head_tail_margin), 2)


def action_beats_for_duration(duration_seconds: float) -> int:
    """按镜头时长给出建议动作拍数（一拍 = 一项物理动作 / 一次主要运镜 / 一句短台词）。"""
    seconds = max(0.0, float(duration_seconds or 0.0))
    if seconds <= 3.0:
        return 1
    if seconds <= 6.0:
        return 2
    return 3


# --------------------------------------------------------------------------- #
# 5. 负面约束（定向 Avoid，不堆砌）
# --------------------------------------------------------------------------- #

NEGATIVE_PROMPT_DISCIPLINE: tuple[str, ...] = (
    "先排除与本镜头直接冲突的内容，再补少量确有风险的缺陷词",
    "不要把所有历史负面词整段粘贴到每个镜头",
    "模型不支持独立负面提示词时，把必要要求改写成正向可见条件",
    "不把「4K/8K」当作清晰度保证：文字的档位不等于实际输出尺寸",
)

# 稳定的身份与连续性护栏（所有题材默认生效）。
DEFAULT_PRESERVE_ITEMS: tuple[str, ...] = (
    "角色的面部、发型、服装与既定外观保持一致",
    "角色在画面中的左右站位与朝向关系不漂移",
    "场景的空间结构、光照方向与主要陈设不重置",
)

# 竖屏短剧最常见的生成缺陷，作为默认定向 Avoid。
DEFAULT_AVOID_ITEMS: tuple[str, ...] = (
    "新增无关人物或改变角色身份",
    "肢体畸形、多指、面部崩坏",
    "画面出现字幕、水印或后期文字叠加",
    "镜头跳变、画面闪烁或主体瞬间变形",
)


# --------------------------------------------------------------------------- #
# 6. 抽象词禁用
# --------------------------------------------------------------------------- #

BANNED_ABSTRACT_WORDS: tuple[str, ...] = (
    "唯美",
    "高级感",
    "氛围感拉满",
    "电影感",
    "大片感",
    "震撼",
    "惊艳",
    "绝美",
    "质感",
    "意境",
    "史诗",
    "顶级",
)

ABSTRACT_WORD_RULE = "用可拍摄的具体视听细节替代抽象形容（不要用「唯美」「电影感」这类词代替设计）"


def find_abstract_words(text: str) -> list[str]:
    """返回文本中命中的抽象词，供质检与模板自检使用。"""
    body = str(text or "")
    return [word for word in BANNED_ABSTRACT_WORDS if word in body]


def is_abstract_only(text: str) -> bool:
    """文本去掉抽象词与空白后是否已无实际信息。"""
    body = str(text or "")
    for word in BANNED_ABSTRACT_WORDS:
        body = body.replace(word, "")
    return not body.strip()


# --------------------------------------------------------------------------- #
# 7. 参考图绑定与画面文字
# --------------------------------------------------------------------------- #

REFERENCE_TOKEN_PREFIX = "图"
MAX_REFERENCE_IMAGES = 9

REFERENCE_BINDING_RULES: tuple[str, ...] = (
    "参考图必须逐张绑定到具体用途，不能只在开头罗列",
    "正文里出现角色时直接写绑定 token（如「图1」），不要含糊写「他/她」",
    "每个镜头自包含：不要写「同上」「沿用上一段参考」",
    "token 顺序与提交给模型的参考图顺序必须完全一致",
)

# 画面文字二分法：后期叠加型默认禁止；剧情内实体文字必须沿用参考资产。
ON_SCREEN_TEXT_RULES: tuple[str, ...] = (
    "字幕、标题、说明卡、贴纸、UI 与水印属于后期叠加，默认不生成",
    "包装、招牌、信件、书页、手机界面等剧情内实体文字，严格保持参考资产的外观，不新增、不改写、不重绘",
)


def build_reference_binding_line(token: str, name: str, kind: str) -> str:
    """生成一行参考图绑定说明。"""
    role_map = {
        "character": "的身份与外观参考（只约束长相、发型、服装，不改变本镜头的动作与构图）",
        "scene": "的空间与光照参考（只约束环境结构，不改变主体动作）",
        "prop": "的外观与结构参考（只约束材质、颜色与形制）",
        "costume": "的服装形制与材质参考",
        "frame": "的画面锚点参考",
    }
    suffix = role_map.get(str(kind or ""), "的参考")
    return f"{token} 为「{name}」{suffix}"


# --------------------------------------------------------------------------- #
# 8. 注入 LLM 的顶层纪律
# --------------------------------------------------------------------------- #

SHORT_DRAMA_SYSTEM_GUIDELINES: tuple[str, ...] = (
    "目标受众为竖屏短剧观众，一律按竖屏构图与短剧节奏写作",
    "情绪写行为不写标签，用可拍摄的动作与微表情承载情绪",
    ("每个镜头都要有明确的信息推进：推进关系、推进认知或推进冲突，不做纯环境展示"),
    ABSTRACT_WORD_RULE,
    *REFERENCE_BINDING_RULES,
)


def summarize_rules(rules: Iterable[str], *, prefix: str = "- ") -> str:
    """把规则列表渲染成可直接嵌进提示词的要点块。"""
    items = [str(rule).strip() for rule in rules if str(rule).strip()]
    return "\n".join(f"{prefix}{item}" for item in items)
