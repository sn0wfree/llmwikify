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
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


# ─── Handler signature ─────────────────────────────────────────────

SyncHandler = Callable[["dict[str, Any]", "SkillContext"], "SkillResult"]
AsyncHandler = Callable[
    ["dict[str, Any]", "SkillContext"],
    Coroutine[Any, Any, "SkillResult"],
]
Handler = SyncHandler | AsyncHandler

# Confirmation policies. Mirrors the existing
# ``WikiToolRegistry.requires_confirmation`` field
# (``False`` / ``True`` / ``"pre"`` / ``"posthoc"``).
ConfirmationPolicy = bool | str


# ─── Result envelope ───────────────────────────────────────────────


@dataclass
class SkillResult:
    """The return type of every skill handler.

    Attributes
    ----------
    status
        One of:

        - ``"ok"``                 - handler succeeded
        - ``"error"``              - handler failed; see ``error``
        - ``"needs_confirmation"`` - handler wants pre-execution
                                     approval; ``confirmation_id``
                                     is set
        - ``"cancelled"``          - handler was cancelled
                                     (e.g. user clicked away)

    data
        Opaque per-skill payload. The LLM-visible schema
        is whatever the skill declared in its description.
    error
        Human-readable error message; populated for ``"error"``
        and ``"needs_confirmation"`` (where it explains why).
    confirmation_id
        Set when ``status == "needs_confirmation"``. The
        confirmation flow uses it to look up the pending
        request.
    """

    status: str = "ok"
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    confirmation_id: str | None = None

    @classmethod
    def ok(cls, data: dict[str, Any] | None = None) -> "SkillResult":
        return cls(status="ok", data=data or {})

    @classmethod
    def fail(cls, error: str, **extra: Any) -> "SkillResult":
        return cls(status="error", error=error, data=dict(extra))

    @classmethod
    def needs_confirmation(
        cls,
        confirmation_id: str,
        message: str = "User approval required",
        **data: Any,
    ) -> "SkillResult":
        return cls(
            status="needs_confirmation",
            error=message,
            confirmation_id=confirmation_id,
            data=dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form. For logging and LLM tool results."""
        out: dict[str, Any] = {"status": self.status, "data": self.data}
        if self.error is not None:
            out["error"] = self.error
        if self.confirmation_id is not None:
            out["confirmation_id"] = self.confirmation_id
        return out


# ─── Action declaration ────────────────────────────────────────────


@dataclass
class SkillAction:
    """One named operation on a skill.

    Attributes
    ----------
    name
        Operation name (verb form). Set automatically by
        ``Skill.actions[name] = SkillAction(...)`` if omitted,
        so most skills just write
        ``"search": SkillAction(handler=..., description=...)``.
    description
        Human/LLM-readable description. Used directly as the
        tool description in the LLM-exposed manifest.
    handler
        Async or sync callable ``(args: dict, ctx: SkillContext)
        -> SkillResult``.
    input_schema
        JSON Schema (Draft 7 subset) describing the args.
        ``{"type": "object", "properties": ..., "required": ...}``
    output_schema
        Optional JSON Schema describing ``data``. Used for
        documentation; the runtime does not validate it.
    requires_confirmation
        One of:

        - ``False``  - execute immediately
        - ``True``   - same as ``"pre"`` (default pre-confirm)
        - ``"pre"``  - require user approval BEFORE running
        - ``"posthoc"`` - run, then log for later review
    action_type
        ``"read"`` or ``"write"``. Drives UI hints and the
        LLM "write operations need confirmation" rule.
    tags
        Free-form labels for filtering (``["low-level"]``,
        ``["crud", "memory"]``, ...). Used by
        ``wiki_query_skill`` to group its 28 actions in
        the manifest.
    """

    name: str = ""
    description: str = ""
    handler: Handler | None = None
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    output_schema: dict[str, Any] | None = None
    requires_confirmation: ConfirmationPolicy = False
    action_type: str = "read"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.handler is None:
            raise ValueError(
                f"SkillAction {self.name!r} requires a handler"
            )
        if self.action_type not in ("read", "write"):
            raise ValueError(
                f"SkillAction {self.name!r}: action_type must be "
                f"'read' or 'write', got {self.action_type!r}"
            )

    @property
    def qualified_name(self) -> str:
        """``"<skill>.<action>"`` - not used internally, but handy
        for logging and test assertions."""
        # The skill name is filled in by the framework during
        # registration; bare SkillAction instances return just
        # the action name.
        return self.name


# ─── Runtime context ───────────────────────────────────────────────


@dataclass
class SkillContext:
    """Per-call context passed to every handler.

    Handlers should not reach back into module globals;
    everything they need (LLM, wiki, db, metrics, config)
    is here. The framework constructs this in the Runtime
    and reuses it across calls within one user request.
    """

    wiki: Any = None
    db: Any = None
    llm_client: Any = None
    config: dict[str, Any] = field(default_factory=dict)
    metrics: Any = None
    session_id: str = ""

    def with_overrides(self, **kwargs: Any) -> "SkillContext":
        """Return a shallow copy with the given fields overridden.

        Useful for tests and for the Runtime to thread a fresh
        ``session_id`` through nested calls without mutating
        the parent's context.
        """
        from dataclasses import replace

        return replace(self, **kwargs)


# ─── Skill ABC ─────────────────────────────────────────────────────


class Skill(ABC):
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
            raise ValueError(
                f"{type(self).__name__} must set class attribute 'name'"
            )
        if not self.actions:
            raise ValueError(
                f"{self.name!r} skill must declare at least one action"
            )
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

    def manifest(self) -> "SkillManifest":
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


__all__ = [
    "Skill",
    "SkillAction",
    "SkillContext",
    "SkillResult",
    "SkillManifest",
    "Handler",
    "SyncHandler",
    "AsyncHandler",
    "ConfirmationPolicy",
]
