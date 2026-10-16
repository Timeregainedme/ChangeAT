"""演员/角色及关联表 schemas。"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.contracts.audio_generation import AudioVoiceSource
from app.models.studio import ProjectStyle, ProjectVisualStyle


class ActorBase(BaseModel):
    id: str = Field(..., description="演员 ID")
    name: str = Field(..., description="名称")
    description: str = Field("", description="描述")
    tags: list[str] = Field(default_factory=list, description="标签")
    prompt_template_id: str | None = Field(None, description="提示词模板 ID（可空）")
    view_count: int = Field(1, ge=1, description="计划为该演员生成的视角图片数量（不含分镜帧）")
    style: ProjectStyle = Field(ProjectStyle.real_people_city, description="题材/风格")
    visual_style: ProjectVisualStyle = Field(ProjectVisualStyle.live_action, description="画面表现形式（真人/动漫等）")
    # 演员默认音色（与 Character 同口径，见 sql/019-add-actor-voice.sql）。
    # 两级结构：演员音色是「这个人」的默认音色，角色音色可覆盖它；解析顺序见
    # app/services/studio/audio_task_runner.py 的 _resolve_audio_voice。
    voice_id: str | None = Field(
        None,
        description="演员默认音色 ID（供应商侧 voice_id）；角色未配音色时，TTS 回退使用该音色",
    )
    voice_source: AudioVoiceSource | None = Field(
        None,
        description="演员默认音色来源：preset 预设音色 / custom 自定义音色；为空时按模型名推断",
    )
    voice_description: str = Field(
        "",
        description="演员音色描述（年龄段/声线/气质/语速等；用于配音选型参考）",
    )


class ActorCreate(ActorBase):
    project_id: str | None = Field(None, description="可选：创建成功后写入 project_actor_links（与演员创建同一事务）")
    chapter_id: str | None = Field(None, description="可选：章节 ID")
    shot_id: str | None = Field(None, description="可选：分镜 ID")

    @field_validator("project_id", "chapter_id", "shot_id", mode="before")
    @classmethod
    def _blank_link_ids(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def _link_scope(self) -> Self:
        if self.chapter_id and not self.project_id:
            raise ValueError("project_id is required when chapter_id is set")
        if self.shot_id and not self.project_id:
            raise ValueError("project_id is required when shot_id is set")
        return self


class ActorUpdate(BaseModel):
    """演员 PATCH 请求体：只声明「允许修改」的字段，全部可选。

    与 `CharacterUpdate` 同理，本类**不继承** `ActorBase`，因此每个可改字段都必须在此
    显式声明；漏声明会让该字段在 PATCH 时被静默忽略（评审 C-3 在角色侧踩过同样的坑）。
    """

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    prompt_template_id: str | None = None
    view_count: int | None = Field(None, ge=1)
    style: ProjectStyle | None = None
    visual_style: ProjectVisualStyle | None = None
    voice_id: str | None = None
    voice_source: AudioVoiceSource | None = None
    voice_description: str | None = Field(
        None,
        description="演员音色描述（年龄段/声线/气质/语速等）；留空表示不改动该字段",
    )


class ActorRead(ActorBase):
    model_config = ConfigDict(from_attributes=True)

    thumbnail: str = Field("", description="缩略图下载地址")


class CharacterBase(BaseModel):
    id: str = Field(..., description="角色 ID")
    project_id: str = Field(..., description="所属项目 ID")
    name: str = Field(..., description="角色名称")
    description: str = Field("", description="角色描述")
    style: ProjectStyle = Field(ProjectStyle.real_people_city, description="题材/风格")
    visual_style: ProjectVisualStyle = Field(ProjectVisualStyle.live_action, description="画面表现形式（现实/动漫等）")
    actor_id: str | None = Field(None, description="演员 ID（可空；用于仅导入角色文案但不关联演员时）")
    costume_id: str | None = Field(None, description="服装 ID（可空）")
    voice_id: str | None = Field(
        None,
        description="角色默认音色 ID（供应商侧 voice_id）；配置后 TTS 未显式传音色时自动使用",
    )
    voice_source: AudioVoiceSource | None = Field(
        None,
        description="角色默认音色来源：preset 预设音色 / custom 自定义音色；为空时按模型名推断",
    )
    voice_description: str = Field(
        "",
        description="角色音色描述（剧本提取产出：年龄段/声线/气质/语速等；用于配音选型参考）",
    )


class CharacterCreate(CharacterBase):
    chapter_id: str | None = Field(None, description="可选：章节 ID")
    shot_id: str | None = Field(None, description="可选：创建成功后自动绑定的分镜 ID")

    @field_validator("project_id", "chapter_id", "shot_id", mode="before")
    @classmethod
    def _blank_link_ids(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def _link_scope(self) -> Self:
        if self.chapter_id and not self.project_id:
            raise ValueError("project_id is required when chapter_id is set")
        if self.shot_id and not self.project_id:
            raise ValueError("project_id is required when shot_id is set")
        return self


class CharacterUpdate(BaseModel):
    """角色 PATCH 请求体：只声明「允许修改」的字段，全部可选。

    为什么存在：与 `CharacterBase` 解耦，避免把 `id` 等不可改字段暴露成可更新项。
    注意本类**不继承** `CharacterBase`，因此每个可改字段都必须在此显式声明；
    漏声明会让该字段在 PATCH 时被静默忽略（评审 C-3：`voice_description` 曾因此改不动，
    与「角色音色描述可查看与修改」的口径不符）。
    """

    project_id: str | None = None
    name: str | None = None
    description: str | None = None
    style: ProjectStyle | None = None
    visual_style: ProjectVisualStyle | None = None
    actor_id: str | None = None
    costume_id: str | None = None
    voice_id: str | None = None
    voice_source: AudioVoiceSource | None = None
    voice_description: str | None = Field(
        None,
        description="角色音色描述（剧本提取产出：年龄段/声线/气质/语速等）；留空表示不改动该字段",
    )


class CharacterRead(CharacterBase):
    model_config = ConfigDict(from_attributes=True)

    thumbnail: str = Field("", description="缩略图下载地址")


class CharacterPropLinkBase(BaseModel):
    id: int = Field(..., description="关联行 ID")
    character_id: str = Field(..., description="角色 ID")
    prop_id: str = Field(..., description="道具 ID")
    index: int = Field(0, description="角色道具排序")
    note: str = Field("", description="备注")


class CharacterPropLinkCreate(BaseModel):
    character_id: str
    prop_id: str
    index: int = 0
    note: str = ""


class CharacterPropLinkUpdate(BaseModel):
    index: int | None = None
    note: str | None = None


class CharacterPropLinkRead(CharacterPropLinkBase):
    model_config = ConfigDict(from_attributes=True)


class ShotCharacterLinkBase(BaseModel):
    id: int = Field(..., description="关联行 ID")
    shot_id: str = Field(..., description="镜头 ID")
    character_id: str = Field(..., description="角色 ID")
    index: int = Field(0, description="镜头内角色排序")
    note: str = Field("", description="备注")


class ShotCharacterLinkCreate(BaseModel):
    shot_id: str
    character_id: str
    index: int = 0
    note: str = ""


class ShotCharacterLinkUpdate(BaseModel):
    index: int | None = None
    note: str | None = None


class ShotCharacterLinkRead(ShotCharacterLinkBase):
    model_config = ConfigDict(from_attributes=True)
