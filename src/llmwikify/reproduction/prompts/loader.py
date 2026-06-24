"""PromptLoader: 从 YAML 文件加载 prompt 模板."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .group import PromptGroup


class PromptLoader:
    """从 base_dir 加载 YAML prompt 文件."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)

    def load(self, filename: str) -> PromptGroup:
        """加载单个 YAML 文件为 PromptGroup."""
        path = self.base_dir / filename
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PromptGroup(
            name=data["name"],
            version=str(data["version"]),
            source=data.get("source", "custom"),
            system=data.get("system", ""),
            user_template=data.get("user_template", ""),
            feedback_template=data.get("feedback_template"),
            metadata=data.get("metadata", {}),
            raw=data,
        )
