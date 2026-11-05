"""Core abstractions for the v0.32 skill framework.

This module defines the four types every skill implementation
reuses:

  - ``Skill``            - abstract base class; subclasses
                           declare a ``name``, a ``description``
                           for the LLM, and a dict of
                           ``SkillAction`` entries.

  - ``SkillAction``      - a single named operation on a skill:
                           an async handler + JSON Schema
                           describing its input + an optional
                           confirmation requirement.

  - ``SkillContext``     - duck-typed runtime context passed
                           to every handler. Carries wiki, db,
                           llm_client, config, metrics, and a
                           session_id so handlers don't reach
                           back into globals.

  - ``SkillResult``      - the return type of every handler:
                           a small envelope (status + data +
                           optional error/confirmation_id).

  - ``SkillManifest``    - a declarative description of a skill
                           for LLM tool generation. Registry
                           turns every registered Skill into
                           one of these.

The framework is **synchronous-handler friendly**: handlers may
be coroutines, plain callables returning a ``SkillResult``,
or methods on the skill instance. The runtime wraps them
uniformly.

Design constraints (per design doc §3.3):

  - One action = one operation, named with a verb (search,
    extract, read, write, plan, analyze, ...).
  - Pipeline skills compose actions via direct Python calls
    (NOT through the LLM); see ``gather_skill`` for the
    canonical example.
  - ``input_schema`` is plain JSON Schema (Draft 7 subset)
    so the existing MCP / agent tool layer can re-use it
    byte-for-byte when exposing skills as LLM tools.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any

# The framework types now live in kernel/skills/types.py (they are
# app-independent, and keeping them here made apps/research depend on
# apps/chat). Re-exported so existing imports keep working.
from llmwikify.kernel.skills.types import (  # noqa: F401
    AsyncHandler,
    ConfirmationPolicy,
    Handler,
    SkillAction,
    SkillContext,
    SkillResult,
    SyncHandler,
)

# ─── Skill ABC ─────────────────────────────────────────────────────


class Skill(ABC):  # noqa: B024
    """Abstract base class for all v0.32 skills.

    Subclasses declare:

    - ``name`` (str, class attribute) — the canonical skill
      identifier (e.g. ``"search"``, ``"wiki_query"``).
    - ``description`` (str, class attribute) — shown to the LLM
      in the manifest.
    - ``actions`` (dict[str, SkillAction], class attribute) —
      the operations this skill exposes.

    Subclasses MAY override ``setup`` (called once at
    registration time) and ``teardown`` (called when the
    registry is cleared) for resource lifecycle.
    """

    name: str = ""
    description: str = ""
    actions: dict[str, SkillAction] = {}

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must set class attribute 'name'")
        if not self.actions:
            raise ValueError(f"{self.name!r} skill must declare at least one action")
        # Fill in action.name from the dict key if not set
        # explicitly. This means most skills just write
        # ``actions = {"search": SkillAction(handler=..., ...)}``
        # without naming the action twice.
        for action_name, action in self.actions.items():
            if not action.name:
                action.name = action_name

    def setup(self) -> None:  # noqa: B027
        """Optional one-time init. Default: no-op."""

    def teardown(self) -> None:  # noqa: B027
        """Optional cleanup. Default: no-op."""

    def get_action(self, name: str) -> SkillAction | None:
        """Look up an action by name. Return None if not found.

        Subclasses MAY override to support dynamic action
        registration, but the default (dict lookup) is
        sufficient for 99% of cases.
        """
        return self.actions.get(name)

    def list_actions(self) -> list[str]:
        """Sorted list of action names. Stable for testing."""
        return sorted(self.actions.keys())

    def manifest(self) -> SkillManifest:
        """Build a ``SkillManifest`` for LLM tool generation.

        The manifest is the public contract: one skill =
        one SkillManifest = N (action_name, description) tuples
        the LLM can call.
        """
        return SkillManifest(
            name=self.name,
            description=self.description,
            actions=[
                {
                    "name": a.name,
                    "description": a.description,
                    "input_schema": a.input_schema,
                    "output_schema": a.output_schema,
                    "action_type": a.action_type,
                    "requires_confirmation": a.requires_confirmation,
                    "tags": list(a.tags),
                }
                for a in self.actions.values()
            ],
        )


# ─── LLM-facing manifest ───────────────────────────────────────────


@dataclass
class SkillManifest:
    """Declarative description of a skill for LLM tool generation.

    Built by ``Skill.manifest()`` and aggregated by
    ``SkillRegistry.all_manifests()`` to derive the
    MCP/agent tool list.
    """

    name: str
    description: str
    actions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def action_count(self) -> int:
        return len(self.actions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "actions": list(self.actions),
        }


class PromptBasedSkill(Skill):
    """Skill driven by markdown instructions (Agent Skills standard).

    Compatible with the Agent Skills convention (agentskills.io):
    ``SKILL.md`` files with YAML frontmatter, filesystem-based
    discovery, progressive disclosure.  The LLM receives the
    instructions and executes them using existing tools.
    """

    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        triggers: list[str] | None = None,
        allowed_tools: list[str] | None = None,
    ):
        self.name = name
        self.description = description
        self.instructions = instructions
        self._triggers = triggers or []
        self._allowed_tools = allowed_tools or []
        self.actions = {
            "execute": SkillAction(
                handler=self._handle_execute,
                description=description,
                triggers=self._triggers,
                trigger_param="input",
                input_schema={
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "User input or command arguments.",
                        },
                    },
                },
                tags=["plugin"],
            ),
        }
        super().__init__()

    async def _handle_execute(
        self, args: dict[str, Any], ctx: SkillContext
    ) -> SkillResult:
        return SkillResult.ok(
            {
                "instructions": self.instructions,
                "allowed_tools": self._allowed_tools,
                "input": args.get("input", ""),
            }
        )


__all__ = [
    "Skill",
    "SkillAction",
    "SkillContext",
    "SkillResult",
    "SkillManifest",
    "PromptBasedSkill",
    "Handler",
    "SyncHandler",
    "AsyncHandler",
    "ConfirmationPolicy",
]
