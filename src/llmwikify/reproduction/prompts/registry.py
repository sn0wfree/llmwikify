"""PromptRegistry: 管理多版本 prompt 模板的注册与查询."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .group import PromptGroup


class PromptRegistry:
    """按 name → [version] 索引 prompt 模板."""

    def __init__(self) -> None:
        self._groups: dict[str, list[PromptGroup]] = defaultdict(list)

    def register(self, group: PromptGroup) -> None:
        """注册一个 prompt 模板."""
        self._groups[group.name].append(group)

    def get(self, name: str, version: str = "latest") -> PromptGroup:
        """获取指定 name+version 的模板, version="latest" 取最新."""
        groups = self._groups.get(name, [])
        if not groups:
            raise KeyError(f"No prompt group named {name!r}")
        if version == "latest":
            return max(groups, key=lambda g: g.version)
        for g in groups:
            if g.version == version:
                return g
        raise KeyError(f"No prompt {name!r} version {version!r}")

    def require(self, name: str, version: str = "latest") -> PromptGroup:
        """同 get, 但缺失时抛 KeyError (语义更明确)."""
        return self.get(name, version)
