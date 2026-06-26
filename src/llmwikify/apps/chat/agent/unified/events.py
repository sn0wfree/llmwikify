"""统一事件常量 — 合并 chat + research，re-export 兼容。

chat events（原有 16 个）+ research events（6 个）统一定义。
research_runner.py 通过 re-export 保持旧 import 路径不变。

用法::

    from llmwikify.apps.chat.agent.unified.events import (
        MESSAGE_DELTA, THINKING, TOOL_CALL_START, DONE, ERROR, PHASE,
        REASONING, ACTION_ERROR, ROUND_COMPLETE,
    )
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

# ── research events（原 research_runner.py EVENT_* 常量）───────
REASONING = "reasoning"
ACTION_ERROR = "action_error"
OBSERVATION_ERROR = "observation_error"
ROUND_COMPLETE = "round_complete"
TIMEOUT = "timeout"


__all__ = [
    # chat
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
    # research
    "REASONING",
    "ACTION_ERROR",
    "OBSERVATION_ERROR",
    "ROUND_COMPLETE",
    "TIMEOUT",
]
