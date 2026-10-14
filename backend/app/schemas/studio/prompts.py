"""提示词模板相关 Pydantic Schemas。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.studio import PromptCategory


class PromptCategoryOptionRead(BaseModel):
    """提示词类别选项（枚举值 + 中文标签 + 简介）。"""

    value: PromptCategory = Field(..., description="类别枚举值")
    label: str = Field(..., description="中文名称")
    description: str = Field("", description="类别简介")


class PromptTemplateCreate(BaseModel):
    """创建提示词模板。id 由后端自动生成；is_system 不可由客户端设置。"""

    category: PromptCategory = Field(..., description="模板类别")
    name: str = Field(..., description="模板名称")
    content: str = Field(..., description="模板内容")
    preview: str = Field("", description="预览文案")
    variables: list[str] = Field(default_factory=list, description="变量名列表")
    is_default: bool = Field(False, description="是否为默认提示词")


class PromptTemplateUpdate(BaseModel):
    """局部更新提示词模板。不含 id / is_system。"""

    name: str | None = Field(None, description="模板名称")
    content: str | None = Field(None, description="模板内容")
    preview: str | None = Field(None, description="预览文案")
    variables: list[str] | None = Field(None, description="变量名列表（整体替换）")
    is_default: bool | None = Field(None, description="是否为默认提示词")


class PromptTemplateRead(BaseModel):
    """读取提示词模板（含全部字段）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="模板 ID")
    category: PromptCategory = Field(..., description="模板类别")
    name: str = Field(..., description="模板名称")
    preview: str = Field(..., description="预览文案")
    content: str = Field(..., description="模板内容")
    variables: list[str] = Field(..., description="变量名列表")
    is_default: bool = Field(..., description="是否为默认提示词")
    is_system: bool = Field(..., description="是否为系统预置")
    published_at: datetime | None = Field(None, description="发布时间（非空 = 已发布到运行时）")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")

