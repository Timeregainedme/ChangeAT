"""实体合并相关的请求/响应模型。

用途：把库里两条同类型实体记录合成一条（数据库层合并），
解决提取阶段 LLM 命名漂移导致的重复资产（如「护工工作服」与「护工护理工作服」）。

与 `script-processing/merge-entities` 的区别：那个是 LLM 语义合并（发生在落库前）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntityMergeRequest(BaseModel):
    """实体合并请求：把 source 合并进 target。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., description="被合并掉的实体 ID（合并完成后该记录被删除）")
    target_id: str = Field(..., description="保留的实体 ID（图片、关联、候选都会迁移到它）")


class EntityMergePairResult(BaseModel):
    """实体合并结果统计。

    字段语义：
    - images_moved：迁到目标实体名下的图片数
    - images_dropped：预留字段，当前始终为 0（不主动删图，避免误删有效素材）
    - links_moved：迁到目标实体的关联数
    - links_dropped：因目标已存在同一作用域关联而删除的重复关联数
    - candidates_repointed：指向目标的提取候选数
    """

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(..., description="实体类型：actor/character/scene/prop/costume")
    source_id: str = Field(..., description="被删除的实体 ID")
    target_id: str = Field(..., description="保留的实体 ID")
    images_moved: int = Field(0, description="迁移的图片数")
    images_dropped: int = Field(0, description="丢弃的图片数（当前始终为 0）")
    links_moved: int = Field(0, description="迁移的关联数")
    links_dropped: int = Field(0, description="因重复而删除的关联数")
    candidates_repointed: int = Field(0, description="重新指向目标实体的提取候选数")
