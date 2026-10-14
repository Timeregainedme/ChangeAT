"""跨镜实体合并 Agent：EntityMergerAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.script_processing import EntityMergeResult

_ENTITY_MERGER_SYSTEM_PROMPT = """\
你是\"实体合并师\"。合并多镜头提取结果，统一实体定义，为每个实体分配ID，识别变体和冲突。
请输出 EntityMergeResult，merged_library 中至少包含 characters/locations/scenes/props 四类。
每个实体条目（EntityEntry）需包含：
- 通用：id/name/type/description/aliases/normalized_name/confidence/first_appearance/evidence/first_shot/appearances/variants
- 角色（type=character）：尽量补充 costume_note、traits
- 地点（type=location）：尽量补充 location_type
- 道具（type=prop）：尽量补充 category、owner_character_id
variants 使用 {variant_key, description, affected_shots, evidence} 的最小结构。
当提供 previous_merge_json 与 conflict_resolutions_json 时，表示这是一次“重试合并”：你必须参考上一次的合并结果与冲突解决建议，优先消解 conflicts；必要时可调整实体合并/拆分策略，但要保持 ID 尽量稳定（除非建议明确要求变更）。
只输出 JSON，符合 EntityMergeResult 结构。
"""

ENTITY_MERGER_PROMPT = PromptTemplate(
    input_variables=[
        "all_extractions_json",
        "historical_library_json",
        "script_division_json",
        "previous_merge_json",
        "conflict_resolutions_json",
    ],
    template=(
        "## 脚本分镜(来自上一步)\n{script_division_json}\n\n"
        "## 所有镜头提取结果\n{all_extractions_json}\n\n"
        "## 历史实体库\n{historical_library_json}\n\n"
        "## 上一次合并结果（可选，用于重试）\n{previous_merge_json}\n\n"
        "## 冲突解决建议（可选，用于重试）\n{conflict_resolutions_json}\n\n"
        "## 输出\n"
    ),
)


class EntityMergerAgent(AgentBase[EntityMergeResult]):

    """跨镜合并 + 基础画像生成：输入全部分镜提取结果+历史实体库，输出合并后的库。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'entity_merge'

    def _default_system_prompt(self) -> str:
        return _ENTITY_MERGER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return ENTITY_MERGER_PROMPT

    @property
    def output_model(self) -> type[EntityMergeResult]:
        return EntityMergeResult

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化实体合并结果。"""
        data = dict(data)
        if "merged_library" not in data:
            data["merged_library"] = {
                "characters": [],
                "locations": [],
                "scenes": [],
                "props": [],
                "total_entries": 0,
            }
        lib = data["merged_library"]
        # 兼容旧字段：缺 locations 时补空；旧结构可能没有 scenes
        if "locations" not in lib:
            lib["locations"] = []
        if "scenes" not in lib:
            lib["scenes"] = []
        if "total_entries" not in lib:
            lib["total_entries"] = sum(
                len(lib.get(k, []) or [])
                for k in ("characters", "locations", "scenes", "props")
            )
        # 兼容旧 variants 结构：dict[] -> EntityVariant[]（最小补齐）
        for bucket_name in ("characters", "locations", "scenes", "props"):
            bucket = lib.get(bucket_name)
            if not isinstance(bucket, list):
                continue
            for ent in bucket:
                if not isinstance(ent, dict):
                    continue
                if "variants" in ent and isinstance(ent["variants"], list):
                    new_vars = []
                    for v in ent["variants"]:
                        if isinstance(v, dict):
                            if "variant_key" not in v:
                                v["variant_key"] = v.get("id") or v.get("key") or "variant"
                            if "affected_shots" not in v:
                                v["affected_shots"] = []
                            if "evidence" not in v:
                                v["evidence"] = []
                            new_vars.append(v)
                        else:
                            new_vars.append(
                                {
                                    "variant_key": "variant",
                                    "description": str(v),
                                    "affected_shots": [],
                                    "evidence": [],
                                }
                            )
                    ent["variants"] = new_vars
        if "merge_stats" not in data:
            data["merge_stats"] = {}
        if "conflicts" not in data or not isinstance(data["conflicts"], list):
            data["conflicts"] = []
        return data

