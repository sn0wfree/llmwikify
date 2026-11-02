"""Chat SSE event type constants — single source of truth.

The chat-side runner (:mod:`runner_v2`) and the orchestrator
(:mod:`orchestrator`) emit these event ``type`` strings. Keeping them
here means the SSE vocabulary has one definition point instead of being
scattered across inline dict literals and the ``ChatEvent`` factory.

The research-side state machine (:mod:`research_runner`) keeps its own
``EVENT_*`` constants on purpose: it is rule-based (not LLM-driven) and
its vocabulary is a v0.50 compatibility contract, so it should not be
merged into this chat vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── session lifecycle ──────────────────────────────────────────
SESSION_CREATED = "session_created"
SESSION_INIT = "session_init"
USER_MESSAGE = "user_message"

# ── streaming output ───────────────────────────────────────────
MESSAGE_DELTA = "message_delta"
THINKING = "thinking"

# ── tool execution ─────────────────────────────────────────────
TOOL_CALL_START = "tool_call_start"
TOOL_CALL_END = "tool_call_end"
TOOL_CALL_ERROR = "tool_call_error"
CONFIRMATION_REQUIRED = "confirmation_required"
COMPACTED = "compacted"

# ── commands / research ────────────────────────────────────────
COMMAND_DONE = "command_done"
RESEARCH_RUN_STARTED = "research_run_started"

# ── terminal ───────────────────────────────────────────────────
DONE = "done"
ERROR = "error"
SAVE_WARNING = "save_warning"

# ── passthrough from LLM stream (consumed by the runner) ───────
PHASE = "phase"


# ══════════════════════════════════════════════════════════════
# Structured contract — the single source for the WebUI types
# ══════════════════════════════════════════════════════════════
#
# The constants above are the wire vocabulary. ``EVENT_SPECS`` adds the
# *payload* of every event, which the WebUI used to write by hand in
# ``ui/webui/src/api.ts`` — that duplication is what drifted (the
# frontend knew 12 of the 17 events, and declared a ``duration_ms``
# on ``confirmation_required`` that no backend emitter ever sends).
#
# ``scripts/gen_webui_types.py`` renders this spec into
# ``ui/webui/src/generated/events.ts``; CI regenerates and diffs it, so
# a new event type cannot reach the frontend as a silent no-op.
#
# Every field is optional unless marked required: an emitter that
# leaves a field out must not break the frontend's type check.


@dataclass(frozen=True)
class EventField:
    """One field of an event payload."""

    name: str
    ts_type: str
    required: bool = True


@dataclass(frozen=True)
class EventSpec:
    """The wire contract of one event.

    ``const`` is the Python constant that holds the wire name,
    ``extends`` names a TypeScript interface the payload is
    intersected with (used by the research status event, whose
    shape is shared with the REST API).
    """

    const: str
    fields: tuple[EventField, ...]
    category: str
    extends: str | None = None


EVENT_SPECS: tuple[EventSpec, ...] = (
    EventSpec(
        "SESSION_CREATED",
        (EventField("session_id", "string"),),
        "session",
    ),
    EventSpec(
        "SESSION_INIT",
        (EventField("session_id", "string"),),
        "session",
    ),
    EventSpec(
        "USER_MESSAGE",
        (EventField("content", "string"),),
        "session",
    ),
    EventSpec(
        "MESSAGE_DELTA",
        (EventField("content", "string"),),
        "stream",
    ),
    EventSpec(
        "THINKING",
        (EventField("content", "string"),),
        "stream",
    ),
    EventSpec(
        "TOOL_CALL_START",
        (
            EventField("tool", "string"),
            EventField("args", "Record<string, unknown>"),
            EventField("call_id", "string"),
        ),
        "tool",
    ),
    EventSpec(
        "TOOL_CALL_END",
        (
            EventField("tool", "string"),
            EventField("result", "unknown"),
            EventField("call_id", "string"),
            EventField("duration_ms", "number"),
        ),
        "tool",
    ),
    EventSpec(
        # runner_v2 omits duration_ms on the error path.
        "TOOL_CALL_ERROR",
        (
            EventField("tool", "string"),
            EventField("error", "string"),
            EventField("call_id", "string"),
            EventField("duration_ms", "number", required=False),
        ),
        "tool",
    ),
    EventSpec(
        # No backend emitter sends duration_ms here — the old hand
        # written frontend type declared it as required.
        "CONFIRMATION_REQUIRED",
        (
            EventField("confirmation_id", "string"),
            EventField("tool", "string"),
            EventField("args", "Record<string, unknown>"),
            EventField("impact", "Record<string, unknown>"),
            EventField("call_id", "string"),
            EventField("duration_ms", "number", required=False),
        ),
        "tool",
    ),
    EventSpec(
        "COMPACTED",
        (
            EventField("call_id", "string"),
            EventField("tool", "string"),
            EventField("chars_saved", "number"),
        ),
        "tool",
    ),
    EventSpec(
        "COMMAND_DONE",
        (
            EventField("command", "string"),
            EventField("ok", "boolean"),
            EventField("message", "string"),
            EventField("data", "unknown", required=False),
        ),
        "command",
    ),
    EventSpec(
        # The payload is the shared research status shape.
        "RESEARCH_RUN_STARTED",
        (),
        "research",
        extends="ResearchRunStatus",
    ),
    EventSpec(
        "DONE",
        (
            EventField("content", "string"),
            EventField("stop_reason", "string", required=False),
            EventField("error", "string", required=False),
            EventField("compacted_count", "number", required=False),
        ),
        "terminal",
    ),
    EventSpec(
        "ERROR",
        (
            EventField("message", "string"),
            EventField("stop_reason", "string", required=False),
        ),
        "terminal",
    ),
    EventSpec(
        "SAVE_WARNING",
        (EventField("reason", "string"),),
        "terminal",
    ),
    EventSpec(
        # The research runner emits the same wire name with three extra
        # fields (round / reason / final_state).
        "PHASE",
        (
            EventField("phase", "string"),
            EventField("round", "number", required=False),
            EventField("reason", "string", required=False),
            EventField("final_state", "unknown", required=False),
        ),
        "terminal",
    ),
)

def _wire_name(const: str) -> str:
    """The wire name of ``const``, or a loud failure if it is gone.

    Looking the constant up in the module globals keeps the spec and
    the constants from drifting apart: renaming a constant without
    updating the spec breaks the import instead of silently changing
    the wire protocol.
    """
    try:
        return globals()[const]
    except KeyError:
        raise NameError(
            f"chat event spec references unknown constant {const!r}"
        ) from None


#: Wire name of every event, in declaration order.
EVENT_NAMES: tuple[str, ...] = tuple(_wire_name(s.const) for s in EVENT_SPECS)


__all__ = [
    "SESSION_CREATED",
    "SESSION_INIT",
    "USER_MESSAGE",
    "MESSAGE_DELTA",
    "THINKING",
    "TOOL_CALL_START",
    "TOOL_CALL_END",
    "TOOL_CALL_ERROR",
    "CONFIRMATION_REQUIRED",
    "COMPACTED",
    "COMMAND_DONE",
    "RESEARCH_RUN_STARTED",
    "DONE",
    "ERROR",
    "SAVE_WARNING",
    "PHASE",
    "EventField",
    "EventSpec",
    "EVENT_SPECS",
    "EVENT_NAMES",
]
