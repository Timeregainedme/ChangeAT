"""Project/Chapter 的请求响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.studio import ChapterStatus, ProjectStyle, ProjectVisualStyle


PROJECT_STYLE_EXAMPLES = [x.value for x in ProjectStyle]


class ProjectBase(BaseModel):
    name: str = Field(..., description="项目名称")
    description: str = Field("", description="项目简介")
    style: ProjectStyle = Field(..., description="题材/风格", examples=PROJECT_STYLE_EXAMPLES)
    visual_style: ProjectVisualStyle = Field(ProjectVisualStyle.live_action, description="画面表现形式")
    seed: int = Field(0, description="随机种子")
    unify_style: bool = Field(True, description="是否统一风格")
    progress: int = Field(0, description="进度百分比（0-100）")
    default_video_ratio: str | None = Field(None, description="项目级默认视频比例；分镜未覆盖时生效")
    default_image_ratio: str | None = Field(None, description="项目级默认图片比例；为空时回落到视频比例")
    default_image_resolution_profile: str | None = Field(
        None, description="项目级默认图片分辨率档位（standard/high）；为空时回落到提供方默认档位"
    )
    use_dialog_audio_as_reference: bool = Field(
        True,
        description=(
            "视频生成时是否自动带上镜头台词已生成的配音作为参考音频"
            "（true=使用，false=纯画面参考）"
        ),
    )
    stats: dict[str, Any] = Field(default_factory=dict, description="聚合统计（JSON）")


class ProjectCreate(ProjectBase):
    id: str = Field(..., description="项目 ID")


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    style: ProjectStyle | None = Field(None, description="题材/风格", examples=PROJECT_STYLE_EXAMPLES)
    visual_style: ProjectVisualStyle | None = None
    seed: int | None = None
    unify_style: bool | None = None
    progress: int | None = None
    default_video_ratio: str | None = None
    default_image_ratio: str | None = None
    default_image_resolution_profile: str | None = None
    use_dialog_audio_as_reference: bool | None = None
    stats: dict[str, Any] | None = None


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: str


class ChapterBase(BaseModel):
    project_id: str = Field(..., description="所属项目 ID")
    index: int = Field(..., description="章节序号（项目内唯一）")
    title: str = Field(..., description="章节标题")
    summary: str = Field("", description="章节摘要")
    raw_text: str = Field("", description="章节原文")
    condensed_text: str = Field("", description="精简原文")
    storyboard_count: int = Field(0, description="分镜数量")
    status: ChapterStatus = Field(ChapterStatus.draft, description="章节状态")


class ChapterCreate(ChapterBase):
    id: str = Field(..., description="章节 ID")


class ChapterUpdate(BaseModel):
    project_id: str | None = None
    index: int | None = None
    title: str | None = None
    summary: str | None = None
    raw_text: str | None = None
    condensed_text: str | None = None
    storyboard_count: int | None = None
    status: ChapterStatus | None = None


class ChapterRead(ChapterBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shot_count: int = Field(0, description="分镜数（shots 条数聚合）")


class StyleOption(BaseModel):
    """通用下拉选项。"""

    value: str = Field(..., description="选项值")
    label: str = Field(..., description="选项展示文案")


class ProjectStyleOptionsRead(BaseModel):
    """项目风格候选项。"""

    visual_styles: list[StyleOption] = Field(default_factory=list, description="视觉风格可选项")
    styles_by_visual_style: dict[str, list[StyleOption]] = Field(
        default_factory=dict,
        description="按视觉风格分组的视频风格选项",
    )
    default_style_by_visual_style: dict[str, str] = Field(
        default_factory=dict,
        description="各视觉风格默认视频风格",
    )


class ProjectProductionReadinessCheck(BaseModel):
    """开工预检单项结果。"""

    key: str = Field(..., description="检查项标识")
    label: str = Field("", description="检查项名称")
    ok: bool = Field(..., description="该项是否通过")
    message: str = Field("", description="结果说明；未通过时给出可执行的修复指引")
    detail: dict[str, Any] = Field(default_factory=dict, description="该项补充数据")


class ProjectProductionReadinessRead(BaseModel):
    """项目开工预检报告（只读聚合，不修改任何状态）。"""

    project_id: str = Field(..., description="项目 ID")
    ready: bool = Field(..., description="是否全部通过，可以开工")
    checks: list[ProjectProductionReadinessCheck] = Field(default_factory=list, description="检查项明细")
    stats: dict[str, Any] = Field(default_factory=dict, description="项目当前规模统计")


class CharacterRecurrenceRead(BaseModel):
    """单个角色的跨集出现情况。

    存在的意义：角色要不要绑定演员取决于它出现在几集里 —— 跨集反复出现的必须绑，
    只在一集内出现的不需要（用户口径 m09145）。把章节数直接给前端，编辑角色时就能标出来。
    """

    character_id: str = Field(..., description="角色 ID")
    chapter_count: int = Field(..., description="该角色出现的去重章节（集）数")
    recurring: bool = Field(..., description="是否为跨集反复出现的主角级角色（需要绑定演员）")


class ProjectCharacterRecurrenceRead(BaseModel):
    """项目下全部角色的跨集出现情况（只读）。"""

    project_id: str = Field(..., description="项目 ID")
    min_chapters: int = Field(..., description="判定为主角级所需的最少章节数")
    items: list[CharacterRecurrenceRead] = Field(default_factory=list, description="角色明细")
