from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import ProjectStyle, ProjectVisualStyle


class Scene(Base, TimestampMixin):
    """场景表。"""

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="描述")
    style: Mapped[ProjectStyle] = mapped_column(String(32), nullable=False, comment="题材/风格")
    view_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="计划为该场景生成的视角图片数量（不含分镜帧）",
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, comment="标签")
    prompt_template_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="提示词模板 ID",
    )
    visual_style: Mapped[ProjectVisualStyle] = mapped_column(
        String(16),
        nullable=False,
        default=ProjectVisualStyle.live_action,
        comment="画面表现形式（现实/动漫等）",
    )

    prompt_template: Mapped["PromptTemplate | None"] = relationship()
    images: Mapped[list["SceneImage"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SceneImage.id",
    )

    __table_args__ = (
        Index("ix_scenes_name", "name"),
        UniqueConstraint("name", name="uq_scenes_name"),
    )


class Prop(Base, TimestampMixin):
    """道具表。角色道具绑定见 CharacterPropLink。"""

    __tablename__ = "props"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="描述")
    style: Mapped[ProjectStyle] = mapped_column(String(32), nullable=False, comment="题材/风格")
    view_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="计划为该道具生成的视角图片数量（不含分镜帧）",
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, comment="标签")
    prompt_template_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="提示词模板 ID",
    )
    visual_style: Mapped[ProjectVisualStyle] = mapped_column(
        String(16),
        nullable=False,
        default=ProjectVisualStyle.live_action,
        comment="画面表现形式（现实/动漫等）",
    )

    prompt_template: Mapped["PromptTemplate | None"] = relationship()
    images: Mapped[list["PropImage"]] = relationship(
        back_populates="prop",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PropImage.id",
    )
    character_prop_links: Mapped[list["CharacterPropLink"]] = relationship(
        back_populates="prop",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_props_name", "name"),
        UniqueConstraint("name", name="uq_props_name"),
    )


class Costume(Base, TimestampMixin):
    """服装表。角色服装见 Character.costume_id。"""

    __tablename__ = "costumes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="描述")
    style: Mapped[ProjectStyle] = mapped_column(String(32), nullable=False, comment="题材/风格")
    view_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="计划为该服装生成的视角图片数量（不含分镜帧）",
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, comment="标签")
    prompt_template_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="提示词模板 ID",
    )
    visual_style: Mapped[ProjectVisualStyle] = mapped_column(
        String(16),
        nullable=False,
        default=ProjectVisualStyle.live_action,
        comment="画面表现形式（现实/动漫等）",
    )

    prompt_template: Mapped["PromptTemplate | None"] = relationship()
    images: Mapped[list["CostumeImage"]] = relationship(
        back_populates="costume",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CostumeImage.id",
    )
    characters: Mapped[list["Character"]] = relationship(back_populates="costume")

    __table_args__ = (
        Index("ix_costumes_name", "name"),
        UniqueConstraint("name", name="uq_costumes_name"),
    )


class Actor(Base, TimestampMixin):
    """演员表（与角色区分）。

    说明：
    - 使用 ActorImage（旧） 的字段集合，作为“演员形象/立绘资产”的主表。
    - 归属由 ProjectActorLink（project/chapter/shot 维度）表达。
    """

    __tablename__ = "actors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="描述")
    style: Mapped[ProjectStyle] = mapped_column(String(32), nullable=False, comment="题材/风格")
    view_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="计划为该演员形象生成的视角图片数量（不含分镜帧）",
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, comment="标签")
    prompt_template_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="提示词模板 ID",
    )
    visual_style: Mapped[ProjectVisualStyle] = mapped_column(
        String(16),
        nullable=False,
        default=ProjectVisualStyle.live_action,
        comment="画面表现形式（现实/动漫等）",
    )
    # 演员默认音色（与 Character 上的三列同口径，见 sql/019-add-actor-voice.sql）。
    # 两级结构：演员音色是「这个人」的默认音色，角色音色可覆盖它。
    # 解析顺序见 app/services/studio/audio_task_runner.py 的 _resolve_audio_voice：
    # 显式 voice → characters.voice_id → 该角色的 actors.voice_id → 422。
    voice_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="演员默认音色 ID（供应商侧 voice_id；为空表示未指定，角色未配音色时回退到此音色）",
    )
    voice_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="演员默认音色来源（preset 预设音色 / custom 自定义音色；为空时按模型名推断）",
    )
    # 口径与 characters.voice_description 一致：ORM 声明 NOT NULL + 客户端默认空串，
    # DDL 侧由 sql/019 收紧为 `TEXT NOT NULL`。不在 DDL 写 DEFAULT 的原因同 018：
    # MySQL 对 BLOB/TEXT 一律不允许 DEFAULT（5.7/8.0 相同）。
    voice_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="演员音色描述（年龄段/声线/气质/语速等；用于配音选型参考）",
    )

    prompt_template: Mapped["PromptTemplate | None"] = relationship()
    images: Mapped[list["ActorImage"]] = relationship(
        back_populates="actor",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ActorImage.id",
    )
    characters: Mapped[list["Character"]] = relationship(back_populates="actor")

    __table_args__ = (
        Index("ix_actors_name", "name"),
        UniqueConstraint("name", name="uq_actors_name"),
    )


class Character(Base, TimestampMixin):
    """角色表（归属项目）。

    组成约定：
    - 角色由：Actor（演员） + Costume（服装） + Props（道具）组成。
    - 最终在分镜中引用角色：`ShotCharacterLink`（shot_character_links）。

    应用层保证：
    - `costume_id` 所指服装应为该角色所属项目或全局资产，避免跨项目误用。
    """

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="角色 ID")
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目 ID",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="角色名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="角色描述")
    style: Mapped[ProjectStyle] = mapped_column(String(32), nullable=False, comment="题材/风格")
    visual_style: Mapped[ProjectVisualStyle] = mapped_column(
        String(16),
        nullable=False,
        default=ProjectVisualStyle.live_action,
        comment="画面表现形式（现实/动漫等）",
    )
    actor_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="对应演员 ID",
    )
    costume_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("costumes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="服装 ID（可空）；应用层需保证与角色同项目或全局",
    )
    voice_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="角色默认音色 ID（供应商侧 voice_id；为空表示未指定，TTS 时须显式传音色）",
    )
    voice_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="角色默认音色来源（preset 预设音色 / custom 自定义音色；为空时按模型名推断）",
    )
    # 音色描述口径（评审 C-3）：这里声明 NOT NULL + 客户端默认空串；DDL 侧由
    # sql/018-unify-character-voice-description-not-null.sql 收紧为 `TEXT NOT NULL` 对齐。
    # 之所以不在 DDL 写 DEFAULT：MySQL 对 BLOB/TEXT 一律不允许 DEFAULT（5.7/8.0 相同），
    # 空串默认值只能由 SQLAlchemy 在 INSERT 时补，从而保证「存入非空、读出非 None」。
    voice_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="角色音色描述（剧本提取产出：年龄段/声线/气质/语速等；用于配音选型参考）",
    )

    project: Mapped["Project"] = relationship(back_populates="characters")
    actor: Mapped["Actor"] = relationship(back_populates="characters")
    costume: Mapped["Costume | None"] = relationship(back_populates="characters")
    prop_links: Mapped[list["CharacterPropLink"]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CharacterPropLink.index",
    )
    shot_links: Mapped[list["ShotCharacterLink"]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    images: Mapped[list["CharacterImage"]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CharacterImage.id",
    )

    __table_args__ = (
        Index("ix_characters_name", "name"),
        UniqueConstraint("project_id", "name", name="uq_characters_project_name"),
    )


class CharacterPropLink(Base,TimestampMixin):
    """角色与道具绑定（多对多）。

    应用层保证：
    - `prop_id` 所指道具应为该角色所属项目或全局资产，避免跨项目误用。
    """

    __tablename__ = "character_prop_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="关联行 ID")
    character_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="角色 ID",
    )
    prop_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("props.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="道具 ID",
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="角色道具排序")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="备注（可选）")

    character: Mapped["Character"] = relationship(back_populates="prop_links")
    prop: Mapped["Prop"] = relationship(back_populates="character_prop_links")

    __table_args__ = (
        UniqueConstraint("character_id", "prop_id", name="uq_character_prop_links_character_prop"),
        UniqueConstraint("character_id", "index", name="uq_character_prop_links_character_index"),
    )


__all__ = [
    "Scene",
    "Prop",
    "Costume",
    "Actor",
    "Character",
    "CharacterPropLink",
]

