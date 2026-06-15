"""Central registry for the v0.32 skill framework.

The registry is a thin, process-wide store of ``Skill`` instances.
It is the single point of truth for "what skills does this
process know about" and powers three consumers:

  - the **Runtime** (looks up ``Skill`` + ``SkillAction`` by
    qualified name and invokes the handler);
  - the **manifest aggregator** (``all_manifests``) that
    builds the LLM tool list;
  - the **MCP / agent tool layer** which derives its 28
    wiki_* tools from the ``wiki_query_skill`` manifest.

Design choices
--------------

  - **Module-level singleton** (``default_registry()``) so
    callers don't have to thread a registry instance
    through every layer. Tests can call ``clear()`` for
    isolation.

  - **Replace-on-conflict** (default): if you register
    ``"search"`` twice, the second wins and a warning is
    logged. This matches the agent tools' current
    "later registration overrides" semantics.

  - **No action-name uniqueness across skills**: action
    names are scoped to their parent skill, so two skills
    may both have a ``"list"`` action. The qualified name
    ``"<skill>.<action>"`` is always unique.

  - **Iterate in registration order** (``__iter__``) so
    manifest ordering is stable for snapshot tests.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillManifest,
)
from llmwikify.apps.chat.skills.errors import (
    ActionNotFoundError,
    SkillNotFoundError,
)

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Process-wide collection of registered ``Skill`` instances.

    Thread-safe: all mutations go through ``self._lock``. Reads
    (``get``, ``list_names``) are also locked for consistency.

    The registry is **not** a singleton by itself — instances
    are cheap, and tests can build a private one. The module
    exposes ``default_registry()`` for the shared instance.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()

    # ── registration ───────────────────────────────────────────

    def register(self, skill: Skill, *, replace: bool = True) -> Skill:
        """Register a skill. Returns the skill (for chaining).

        If ``replace=False`` and the name is already taken,
        raises ``ValueError`` (useful for production startup
        checks). Default ``replace=True`` matches the agent
        tools' "later wins" semantics.
        """
        if not isinstance(skill, Skill):
            raise TypeError(
                f"register() requires a Skill instance, got "
                f"{type(skill).__name__}"
            )
        with self._lock:
            if skill.name in self._skills and not replace:
                raise ValueError(
                    f"Skill {skill.name!r} already registered "
                    f"(pass replace=True to override)"
                )
            if skill.name in self._skills:
                logger.warning(
                    "Replacing already-registered skill %r", skill.name
                )
            self._skills[skill.name] = skill
        try:
            skill.setup()
        except Exception as e:
            logger.error(
                "Skill %r setup() failed: %s", skill.name, e, exc_info=True
            )
            raise
        return skill

    def unregister(self, name: str) -> Skill | None:
        """Remove a skill. Returns the removed skill or None."""
        with self._lock:
            skill = self._skills.pop(name, None)
        if skill is not None:
            try:
                skill.teardown()
            except Exception as e:
                logger.warning(
                    "Skill %r teardown() failed: %s", name, e, exc_info=True
                )
        return skill

    def clear(self) -> None:
        """Remove all skills. Tests use this for isolation."""
        with self._lock:
            names = list(self._skills.keys())
            for name in names:
                skill = self._skills.pop(name)
                try:
                    skill.teardown()
                except Exception:
                    pass

    # ── lookup ─────────────────────────────────────────────────

    def get(self, name: str) -> Skill | None:
        """Return the skill registered under ``name`` (or None)."""
        with self._lock:
            return self._skills.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._skills

    def list_names(self) -> list[str]:
        """Sorted list of registered skill names."""
        with self._lock:
            return sorted(self._skills.keys())

    def find_action(
        self, skill_name: str, action_name: str
    ) -> tuple[Skill, SkillAction]:
        """Look up ``(skill, action)`` by qualified name.

        Raises ``SkillNotFoundError`` if the skill is unknown
        and ``ActionNotFoundError`` if the skill is known but
        has no such action.
        """
        skill = self.get(skill_name)
        if skill is None:
            raise SkillNotFoundError(skill_name)
        action = skill.get_action(action_name)
        if action is None:
            raise ActionNotFoundError(skill_name, action_name)
        return skill, action

    def parse_qualified(self, qualified: str) -> tuple[str, str]:
        """Parse ``"skill_name.action_name"`` into a tuple.

        Raises ``ValueError`` for malformed input.
        """
        if "." not in qualified:
            raise ValueError(
                f"Qualified skill name must be 'skill.action', "
                f"got {qualified!r}"
            )
        skill_name, action_name = qualified.split(".", 1)
        if not skill_name or not action_name:
            raise ValueError(
                f"Qualified skill name must have non-empty "
                f"skill and action parts, got {qualified!r}"
            )
        return skill_name, action_name

    # ── manifest aggregation ──────────────────────────────────

    def all_manifests(self) -> list[SkillManifest]:
        """List of manifests in stable (sorted) skill order.

        The order is sorted by skill name to make snapshot
        tests deterministic. The 28-action manifest for
        ``wiki_query`` will be a single entry here.
        """
        with self._lock:
            names = sorted(self._skills.keys())
            return [self._skills[n].manifest() for n in names]

    def all_actions(
        self, *, tag: str | None = None
    ) -> list[tuple[str, SkillAction]]:
        """Flatten all (skill_name, action) pairs.

        With ``tag="read-only"`` (or any tag), only actions
        carrying that tag are returned. The LLM tool-list
        builder uses this to filter by capability.
        """
        out: list[tuple[str, SkillAction]] = []
        with self._lock:
            names = sorted(self._skills.keys())
            for name in names:
                for action in self._skills[name].actions.values():
                    if tag is None or tag in action.tags:
                        out.append((name, action))
        return out

    # ── trigger aggregation ────────────────────────────────────

    def all_triggers(self) -> list[dict[str, str]]:
        """Collect all triggers from all registered skills.

        Returns a list of dicts, each containing:
          - ``trigger``: the trigger string (e.g. ``"/study"``)
          - ``tool``: the tool name to invoke (``"skill_action"``)
          - ``param``: the parameter name for the trigger value
          - ``skill``: the skill name
          - ``action``: the action name
          - ``description``: short description

        The LLM-exposed ``get_skill_commands`` tool returns
        this list so the model can map user commands to tools.
        """
        out: list[dict[str, str]] = []
        with self._lock:
            names = sorted(self._skills.keys())
            for name in names:
                skill = self._skills[name]
                for action in skill.actions.values():
                    for trigger in action.triggers:
                        out.append(
                            {
                                "trigger": trigger,
                                "tool": "skill_action",
                                "param": action.trigger_param,
                                "skill": name,
                                "action": action.name,
                                "description": action.description[:100],
                            }
                        )
        return out

    # ── iteration ─────────────────────────────────────────────

    def __iter__(self) -> Iterator[Skill]:
        with self._lock:
            return iter(list(self._skills.values()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._skills)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return self.has(name)


# ── default singleton ────────────────────────────────────────────


_default: SkillRegistry | None = None
_default_lock = threading.Lock()


def default_registry() -> SkillRegistry:
    """Return the process-wide default registry.

    Lazy-initialized and cached. Tests that need isolation
    should construct their own ``SkillRegistry()`` instance
    rather than calling ``default_registry().clear()``
    (which would also drop skills registered by the test
    harness).
    """
    global _default
    with _default_lock:
        if _default is None:
            _default = SkillRegistry()
        return _default


def reset_default_registry() -> SkillRegistry:
    """Force-replace the default registry. Returns the new one.

    Use only in test setup/teardown. Production code should
    just call ``default_registry()`` and let it lazy-init.
    """
    global _default
    with _default_lock:
        _default = SkillRegistry()
        return _default


__all__ = [
    "SkillRegistry",
    "default_registry",
    "reset_default_registry",
]
