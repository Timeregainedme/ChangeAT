"""提示词中间表示（IR）、渲染器与短剧规则常量层。

子模块职责：

- `short_drama_rules`：红果向短剧的创作纪律常量与纯函数（无 IO、无 LLM）。
- `ir`：提示词 IR 数据模型与构建函数，把业务数据整理成结构化文档。
- `renderers`：把同一份 IR 输出为目标模型所需格式（H3 英文六段式等）。
"""

from app.chains.prompts import short_drama_rules  # noqa: F401

__all__ = ["short_drama_rules"]
