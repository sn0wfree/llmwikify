"""Built-in workflows: `llmwikify-research` — 7-step research pipeline.

This is the v1 reference implementation: planner → 4 parallel
researchers → adversarial verifier → synthesizer.

It mirrors the structure described in
``docs/dynamic-workflow-dsl.md`` §4 and the Claude Code feature
described in ``docs/dynamic-workflows-research.md`` §11.

The 4 actor prompt bodies live in
``apps/chat/skills/workflows/actor_prompts/*.md``. They are pure
markdown with JSON-only output contracts.
"""
from __future__ import annotations

# This file is the loader for built-in workflows. Each workflow is
# a YAML file under apps/chat/skills/workflows/builtins/. We
# intentionally keep one Python entry point that knows how to
# locate and load them, so that the dynamic_workflow skill can
# offer a "list builtins" action and a "run by name" action
# without scanning the filesystem on every call.
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.skills.workflows.dag import (
    WorkflowSpec,
    load_workflow,
)

logger = logging.getLogger(__name__)


_BUILTINS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class BuiltinWorkflow:
    name: str
    description: str
    path: Path
    spec: WorkflowSpec

    @property
    def actor_names(self) -> tuple[str, ...]:
        return tuple(self.spec.actors.keys())

    @property
    def phase_count(self) -> int:
        return len(self.spec.phases)


def iter_builtins() -> Iterator[BuiltinWorkflow]:
    """Yield every built-in workflow in deterministic order."""
    for path in sorted(_BUILTINS_DIR.glob("*.yaml")):
        try:
            spec = load_workflow(path)
        except Exception as e:  # pragma: no cover
            logger.error("failed to load builtin workflow %s: %s", path, e)
            continue
        yield BuiltinWorkflow(
            name=spec.name,
            description=spec.description,
            path=path,
            spec=spec,
        )


def get_builtin(name: str) -> BuiltinWorkflow | None:
    """Look up a built-in by its ``workflow.name``. Returns None if missing."""
    for w in iter_builtins():
        if w.name == name:
            return w
    return None


def list_builtin_names() -> list[str]:
    return [w.name for w in iter_builtins()]


def load_actor_prompt(actor_name: str, base_dir: Path | None = None) -> str:
    """Load an actor's prompt body by name.

    Falls back to looking under the builtins/ directory when no
    caller-supplied base_dir is given.
    """
    candidates: list[Path] = []
    if base_dir is not None:
        candidates.append(base_dir / "actor_prompts" / f"{actor_name}.md")
        candidates.append(base_dir / f"{actor_name}.md")
    candidates.append(_BUILTINS_DIR / "actor_prompts" / f"{actor_name}.md")
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"actor prompt {actor_name!r} not found. Tried: "
        f"{[str(c) for c in candidates]}"
    )


__all__ = [
    "BuiltinWorkflow",
    "iter_builtins",
    "get_builtin",
    "list_builtin_names",
    "load_actor_prompt",
]
