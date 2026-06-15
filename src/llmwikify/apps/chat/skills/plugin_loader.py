"""Plugin loader — discover and register skills from ~/.llmwikify/skills/.

Supports two paradigms:

  - **Prompt-Based** (Agent Skills standard): a folder containing
    ``SKILL.md`` with YAML frontmatter.  The skill is registered
    as a ``PromptBasedSkill`` whose handler returns the markdown
    instructions for the LLM to follow.

  - **Code-Based**: a ``*.py`` file that defines a ``Skill``
    subclass (or exposes a module-level ``skill`` variable).
    The file is imported dynamically and registered directly.

Folder layout::

    ~/.llmwikify/skills/
    ├── study/
    │   └── SKILL.md          ← Prompt-Based
    ├── my_tool.py            ← Code-Based
    └── another-skill/
        ├── SKILL.md
        └── scripts/
            └── helper.sh
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmwikify.apps.chat.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path.home() / ".llmwikify" / "skills"


def load_plugins(registry: "SkillRegistry") -> int:
    """Scan ``~/.llmwikify/skills/`` and register discovered skills.

    Returns the number of skills successfully loaded.
    """
    if not PLUGIN_DIR.exists():
        return 0

    loaded = 0
    for item in sorted(PLUGIN_DIR.iterdir()):
        try:
            if item.is_dir() and (item / "SKILL.md").exists():
                _load_skill_md(item, registry)
                loaded += 1
            elif item.suffix == ".py" and not item.name.startswith("_"):
                _load_python_skill(item, registry)
                loaded += 1
        except Exception:
            logger.warning(
                "Failed to load plugin %s", item.name, exc_info=True
            )
    if loaded:
        logger.info("Loaded %d plugin skill(s) from %s", loaded, PLUGIN_DIR)
    return loaded


def _load_skill_md(skill_dir: Path, registry: "SkillRegistry") -> None:
    """Load a Prompt-Based skill from a ``SKILL.md`` file."""
    from llmwikify.apps.chat.skills.base import PromptBasedSkill

    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    meta: dict = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()

    name = meta.get("name", skill_dir.name)
    description = meta.get("description", f"Plugin skill: {name}")
    triggers = meta.get("triggers", [])
    allowed_tools = meta.get("allowed-tools", [])

    skill = PromptBasedSkill(
        name=name,
        description=description,
        instructions=body,
        triggers=triggers,
        allowed_tools=allowed_tools,
    )
    registry.register(skill)
    logger.debug(
        "Loaded Prompt-Based plugin: %s (triggers=%s)", name, triggers
    )


def _load_python_skill(py_path: Path, registry: "SkillRegistry") -> None:
    """Load a Code-Based skill from a Python file."""
    from llmwikify.apps.chat.skills.base import Skill

    module_name = f"_plugin_{py_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {py_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Look for a module-level `skill` variable first
    skill_obj = getattr(module, "skill", None)
    if skill_obj is not None and isinstance(skill_obj, Skill):
        registry.register(skill_obj)
        logger.debug("Loaded Code-Based plugin (skill var): %s", py_path.name)
        return

    # Otherwise, look for a Skill subclass
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, Skill)
            and attr is not Skill
        ):
            try:
                instance = attr()
                registry.register(instance)
                logger.debug(
                    "Loaded Code-Based plugin (class): %s", py_path.name
                )
                return
            except Exception:
                logger.debug(
                    "Skipping %s: instantiation failed", attr_name
                )

    raise ImportError(
        f"No Skill subclass or `skill` variable found in {py_path.name}"
    )


__all__ = ["load_plugins", "PLUGIN_DIR"]
