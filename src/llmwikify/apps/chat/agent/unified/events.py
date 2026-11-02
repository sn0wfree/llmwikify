"""Event constants — backward-compat re-export.

The chat SSE vocabulary lives in
:mod:`llmwikify.apps.chat.agent.events` (the single source the WebUI
types are generated from) and the research-runner vocabulary lives in
:mod:`llmwikify.apps.chat.agent.research_runner`. This module used to
define its own copies of both, which is how the frontend and the
backend drifted apart.

It now only re-exports, so the old import path keeps working while
there is exactly one definition of every event name.

Usage::

    from llmwikify.apps.chat.agent.unified.events import (
        MESSAGE_DELTA, THINKING, TOOL_CALL_START, DONE, ERROR, PHASE,
        REASONING, ACTION_ERROR, ROUND_COMPLETE,
    )
"""

from __future__ import annotations

from llmwikify.apps.chat.agent.events import (
    COMMAND_DONE,
    COMPACTED,
    CONFIRMATION_REQUIRED,
    DONE,
    ERROR,
    MESSAGE_DELTA,
    PHASE,
    RESEARCH_RUN_STARTED,
    SAVE_WARNING,
    SESSION_CREATED,
    SESSION_INIT,
    THINKING,
    TOOL_CALL_END,
    TOOL_CALL_ERROR,
    TOOL_CALL_START,
    USER_MESSAGE,
)
from llmwikify.apps.chat.agent.research_runner import (
    EVENT_ACTION_ERROR as ACTION_ERROR,
)
from llmwikify.apps.chat.agent.research_runner import (
    EVENT_OBSERVATION_ERROR as OBSERVATION_ERROR,
)
from llmwikify.apps.chat.agent.research_runner import (
    EVENT_REASONING as REASONING,
)
from llmwikify.apps.chat.agent.research_runner import (
    EVENT_ROUND_COMPLETE as ROUND_COMPLETE,
)
from llmwikify.apps.chat.agent.research_runner import (
    EVENT_TIMEOUT as TIMEOUT,
)

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
