"""供应商能力覆盖的通用前缀匹配存储。

用途：
- 内置供应商（OpenAI / 火山引擎）各自维护专属能力模块；
- 新增供应商（PIX / 优云智算等）可直接复用一个「默认能力 + 按模型前缀覆盖」的存储，
  避免为每个供应商复制一遍 `_pick_override` 逻辑。

匹配规则：模型名（小写）以某个已注册前缀开头即命中，**最长前缀优先**，
避免通用前缀覆盖更具体的前缀。
"""

from __future__ import annotations

from typing import Generic, TypeVar

CapabilityT = TypeVar("CapabilityT")


class PrefixCapabilityStore(Generic[CapabilityT]):
    """默认能力 + 按模型前缀覆盖的能力存储。"""

    def __init__(self, *, provider: str, default: CapabilityT) -> None:
        self.provider = provider
        self._default = default
        self._overrides: dict[str, CapabilityT] = {}

    @property
    def default(self) -> CapabilityT:
        return self._default

    def register(self, *, model_prefix: str, capability: CapabilityT) -> None:
        prefix = (model_prefix or "").strip().lower()
        if not prefix:
            raise ValueError("model_prefix must not be empty")
        self._overrides[prefix] = capability

    def clear(self) -> None:
        self._overrides.clear()

    def resolve(self, model: str | None) -> CapabilityT:
        override = self._pick_override(model)
        return override if override is not None else self._default

    def _pick_override(self, model: str | None) -> CapabilityT | None:
        if not model:
            return None
        value = model.strip().lower()
        if not value:
            return None
        for prefix, capability in sorted(self._overrides.items(), key=lambda item: len(item[0]), reverse=True):
            if value.startswith(prefix):
                return capability
        return None
