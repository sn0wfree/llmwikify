"""PromptStore: 管理 prompt 模板的存储路径."""
from __future__ import annotations

from pathlib import Path

from .loader import PromptLoader
from .registry import PromptRegistry


class PromptStore:
    """管理 builtin + 自定义 prompt 的加载与注册."""

    def __init__(self, custom_dir: Path | str | None = None) -> None:
        self.builtin_dir = Path(__file__).parent / "builtin"
        self.custom_dir = Path(custom_dir) if custom_dir else None
        self.registry = PromptRegistry()

    def load_builtin(self) -> PromptRegistry:
        """加载 builtin/ 下所有 YAML prompt."""
        if not self.builtin_dir.exists():
            return self.registry
        loader = PromptLoader(self.builtin_dir)
        for yaml_file in sorted(self.builtin_dir.glob("*.yaml")):
            group = loader.load(yaml_file.name)
            self.registry.register(group)
        return self.registry
