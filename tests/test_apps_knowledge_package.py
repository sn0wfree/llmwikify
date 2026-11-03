"""Tests for the shared ``apps.knowledge`` substrate.

``apps/knowledge`` is what breaks the ``apps.chat`` ↔ ``apps.research``
cycle: the parts both sides need live there, so neither has to import
the other.

The back-compat shims must expose the **same module objects** — if they
did not, every ``mock.patch("llmwikify.apps.research.web_search....")``
in the test suite would silently stop patching anything.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

CANONICAL = {
    "web_search": "llmwikify.apps.knowledge.web_search",
    "base": "llmwikify.apps.knowledge.base",
    "db": "llmwikify.apps.knowledge.db",
}

SHIMS = {
    "web_search": "llmwikify.apps.research.web_search",
    "base": "llmwikify.apps.research.base",
    "db": "llmwikify.apps.research.db",
}


# ── the package exists and exports the shared surface ───────────────


def test_knowledge_package_exports() -> None:
    """The shared names are importable from the package root."""
    from llmwikify.apps import knowledge

    for name in (
        "BaseGateResult",
        "BaseQualityGate",
        "BaseResearchConfig",
        "BaseResearchTaskManager",
        "ResearchDatabase",
        "WebSearch",
    ):
        assert hasattr(knowledge, name), f"apps.knowledge.{name} is missing"


def test_knowledge_does_not_import_its_siblings() -> None:
    """The substrate is below both packages — it may import neither."""
    from llmwikify.apps import knowledge

    package_dir = Path(knowledge.__file__).parent
    offenders: list[str] = []
    for path in package_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for sibling in ("chat", "research"):
            if f"llmwikify.apps.{sibling}" in text:
                offenders.append(f"{path.name} → apps.{sibling}")
    assert not offenders, offenders


# ── the back-compat shims are the same module objects ──────────────


@pytest.mark.parametrize("name", sorted(CANONICAL))
def test_shim_is_the_same_module_object(name: str) -> None:
    """The old path and the new path are one module, not two copies.

    This is what keeps ``mock.patch`` on either path working.
    """
    canonical = importlib.import_module(CANONICAL[name])
    shim = importlib.import_module(SHIMS[name])
    assert shim is canonical


@pytest.mark.parametrize("name", sorted(CANONICAL))
def test_shim_is_registered_in_sys_modules(name: str) -> None:
    """The ``sys.modules`` alias is in place, not just an attribute copy."""
    canonical = importlib.import_module(CANONICAL[name])
    assert sys.modules[SHIMS[name]] is canonical


def test_research_package_still_exports_the_public_names() -> None:
    """``apps.research`` keeps its public surface."""
    from llmwikify.apps import research

    assert research.WebSearch.__name__ == "WebSearch"
    assert research.ResearchDatabase.__name__ == "ResearchDatabase"


def test_chat_package_still_exports_the_public_names() -> None:
    """``apps.chat`` keeps its public surface (lazy attributes)."""
    from llmwikify.apps import chat

    assert chat.WebSearch.__name__ == "WebSearch"
    assert chat.ResearchDatabase.__name__ == "ResearchDatabase"
    assert chat.ResearchAgent.__name__ == "ResearchAgent"


def test_research_agent_moved_to_the_research_package() -> None:
    """The research agent belongs with the research engine."""
    from llmwikify.apps.chat.research_agent import ResearchAgent as FromChat
    from llmwikify.apps.research.agent import ResearchAgent as FromResearch

    assert FromChat is FromResearch


# ── the config defaults still load ─────────────────────────────────


def test_research_defaults_yaml_is_found() -> None:
    """The defaults YAML must sit next to the module that loads it.

    Regression net: moving ``base.py`` without moving
    ``config_defaults.yaml`` silently emptied the research defaults —
    the merge helper returned a config without a single key.
    """
    from llmwikify.apps.knowledge import base

    defaults = base._load_research_defaults()
    assert defaults, "the research defaults YAML was not found"
    assert "search_provider" in defaults


def test_config_defaults_yaml_ships_with_the_package() -> None:
    """The YAML must be declared as package data, or the wheel loses it."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"llmwikify.apps.knowledge" = [ "config_defaults.yaml",]' in pyproject


def test_the_yaml_is_next_to_the_module() -> None:
    """The loader resolves the YAML relative to its own module."""
    from llmwikify.apps.knowledge import base

    module_dir = Path(base.__file__).parent
    assert (module_dir / "config_defaults.yaml").exists()
