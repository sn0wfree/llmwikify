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
]
