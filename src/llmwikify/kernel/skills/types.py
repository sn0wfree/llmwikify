"""Skill framework types — generic, app-independent.

``SkillResult`` / ``SkillAction`` / ``SkillContext`` describe the
skill contract itself. They used to live in
``apps/chat/skills/base.py``, which made the research engine
depend on the chat app. They live here so both can use them.
"""

from __future__ import annotations

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
    def ok(cls, data: dict[str, Any] | None = None) -> SkillResult:
        return cls(status="ok", data=data or {})

    @classmethod
    def fail(cls, error: str, **extra: Any) -> SkillResult:
        return cls(status="error", error=error, data=dict(extra))

    @classmethod
    def needs_confirmation(
        cls,
        confirmation_id: str,
        message: str = "User approval required",
        **data: Any,
    ) -> SkillResult:
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
    triggers
        Command strings that invoke this action (e.g.
        ``["/study", "研究："]``).  Matched against user
        input by the ``get_skill_commands`` tool.
    trigger_param
        Which input parameter the trigger value is mapped to
        (default ``"question"``).
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
    triggers: list[str] = field(default_factory=list)
    trigger_param: str = "question"

    def __post_init__(self) -> None:
        if self.handler is None:
            raise ValueError(f"SkillAction {self.name!r} requires a handler")
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
    llm_spec: Any = None
    config: dict[str, Any] = field(default_factory=dict)
    metrics: Any = None
    session_id: str = ""
    # Issue#2: optional side-channel emit callback for real-time event
    # propagation. Handlers can call ctx.emit(ev) to forward events to
    # the SSE consumer immediately, without buffering until the action
    # completes. When None, falls back to the legacy buffered path
    # (events collected in result.data["_events"]).
    emit: Any = None

    def with_overrides(self, **kwargs: Any) -> SkillContext:
        """Return a shallow copy with the given fields overridden.

        Useful for tests and for the Runtime to thread a fresh
        ``session_id`` through nested calls without mutating
        the parent's context.
        """
        from dataclasses import replace

        return replace(self, **kwargs)
