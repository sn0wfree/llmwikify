"""Verify autoresearch no longer imports from the deprecated agent backend.

Phase 1 #1 / C3 — autoresearch modules now import StreamableLLMClient
from ``llmwikify.foundation.llm.streamable`` (the canonical home) rather than
``llmwikify.agent.backend.adapters`` (the deprecated home).

The remaining deprecation warning in this codebase is for
``llmwikify.agent.backend.providers.registry`` — that's a different
code path that will be revisited in C5 (the agent provider system
stays inside the agent module for now, per the plan).
"""

from __future__ import annotations

import ast
from pathlib import Path


# Resolve autoresearch dir relative to this file so the test is
# stable when other tests in the same suite chdir or monkeypatch cwd.
_AUTORESEARCH_DIR = (
    Path(__file__).parent.parent / "src" / "llmwikify" / "apps" / "chat"
)
DEPRECATED_PATH = "llmwikify.agent.backend.adapters"


def _imports_from(path: Path, module: str) -> list[str]:
    """Return line numbers (1-indexed) in ``path`` that import ``module``."""
    tree = ast.parse(path.read_text())
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            line = node.lineno
            hits.append(f"{path.name}:{line}")
    return hits


def test_autoresearch_does_not_import_from_deprecated_adapters():
    """No autoresearch file imports from the deprecated adapters module."""
    py_files = list(_AUTORESEARCH_DIR.glob("*.py"))
    assert py_files, f"no .py files in {_AUTORESEARCH_DIR}"

    hits: list[str] = []
    for p in py_files:
        hits.extend(_imports_from(p, DEPRECATED_PATH))
    assert hits == [], (
        f"autoresearch still imports from deprecated {DEPRECATED_PATH}: {hits}"
    )


def test_autoresearch_engine_imports_streamable_from_new_home():
    """engine.py uses the new home for StreamableLLMClient.

    The v0.41 ResearchEngine was moved to ``archive/llmwikify_v0_41_legacy``
    in B-7 (2026-06-18); the test reads the archived source directly to
    avoid the (no longer needed) module-level import chain.
    """
    engine_path = (
        Path(__file__).parent.parent
        / "src"
        / "llmwikify"
        / "archive"
        / "llmwikify_v0_41_legacy"
        / "chat_legacy"
        / "engine.py"
    )
    src = engine_path.read_text()
    assert "from llmwikify.foundation.llm.streamable import StreamableLLMClient" in src
    assert "from llmwikify._legacy.adapters import" not in src


def test_autoresearch_actions_imports_streamable_from_new_home():
    """actions.py uses the new home for StreamableLLMClient."""
    from llmwikify.apps.chat import actions

    src = Path(actions.__file__).read_text()
    assert "from llmwikify.foundation.llm.streamable import StreamableLLMClient" in src
    assert "from llmwikify._legacy.adapters import" not in src


def test_autoresearch_engine_helpers_docstring_updated():
    """engine_helpers.py no longer references the deprecated path in its docs."""
    from llmwikify.apps.chat import engine_helpers

    src = Path(engine_helpers.__file__).read_text()
    assert "agent.backend.adapters" not in src
    assert "llmwikify.foundation.llm.streamable" in src
