"""PromptGroup: 单个 prompt 模板的版本化容器."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .renderer import render_template


@dataclass
class PromptGroup:
    """一个 prompt 模板的完整定义 (system + user + feedback)."""

    name: str
    version: str
    source: str
    system: str
    user_template: str
    feedback_template: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def render_user(self, **kwargs: Any) -> str:
        """渲染 user_template."""
        return render_template(self.user_template, **kwargs)

    def render_feedback(self, **kwargs: Any) -> str:
        """渲染 feedback_template (缺失时抛错)."""
        if self.feedback_template is None:
            raise ValueError(
                f"PromptGroup {self.name!r} has no feedback_template"
            )
        return render_template(self.feedback_template, **kwargs)

    def is_compatible(self, min_version: str) -> bool:
        """semver 兼容性: major 相同即可."""
        def _parse(v: str) -> tuple[int, int, int]:
            parts = v.split(".")
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        cur = _parse(self.version)
        req = _parse(min_version)
        return cur[0] == req[0] and cur >= req
