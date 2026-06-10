"""Shared bridge for translating ReActEngine events to legacy SSE format.

Used by both:
  - apps/research/engine.py::ResearchEngine
  - apps/chat/engine.py::ResearchEngine

Extracts the common event translation logic that would otherwise be
duplicated across both engines.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

logger = logging.getLogger(__name__)


async def translate_react_events(
    engine_events: AsyncIterator[dict[str, Any]],
    *,
    state: Any,
    session_id: str,
    timeout_seconds: float,
    update_status: Callable[[str, str, str, int], None],
    action_done_handler: Callable[[Any], AsyncIterator[dict[str, Any]]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Translate ReActEngine events to legacy SSE format.

    Args:
        engine_events: Raw events from ReActEngine.run().
        state: ResearchState (dataclass or dict) with .round, .phase, .max_rounds.
        session_id: Current session ID for status updates.
        timeout_seconds: Research timeout for error messages.
        update_status: Callable to update session status in DB.
        action_done_handler: Optional async iterator for legacy 'done' event
            (research engine needs this; chat engine doesn't).
    """
    async for event in engine_events:
        event_type = event.get("type")

        if event_type == "phase":
            phase = event.get("phase")
            reason = event.get("reason")

            if phase == "cancelled":
                round_idx = getattr(state, "round", state.get("round", 0) if isinstance(state, dict) else 0)
                phase_name = getattr(state, "phase", state.get("phase", "") if isinstance(state, dict) else "")
                yield {"type": "cancelled", "round": round_idx, "phase": phase_name}
                update_status(session_id, "cancelled", phase_name, -1)

            elif phase == "paused":
                round_idx = getattr(state, "round", state.get("round", 0) if isinstance(state, dict) else 0)
                phase_name = getattr(state, "phase", state.get("phase", "") if isinstance(state, dict) else "")
                yield {"type": "paused", "round": round_idx, "phase": phase_name}
                update_status(session_id, "paused", phase_name, round_idx)

            elif phase == "timeout":
                yield {"type": "error", "error": f"Research timed out after {timeout_seconds}s"}
                update_status(session_id, "timeout", getattr(state, "phase", ""), -1)

            elif phase == "done" and reason == "max_rounds":
                round_idx = getattr(state, "round", state.get("round", 0) if isinstance(state, dict) else 0)
                max_rounds = getattr(state, "max_rounds", state.get("max_rounds", 0) if isinstance(state, dict) else 0)
                yield {"type": "round_max", "round": round_idx, "message": f"Reached max rounds ({max_rounds})"}

            elif phase == "done" and reason == "reason_returned_done" and action_done_handler is not None:
                async for done_ev in action_done_handler(state):
                    yield done_ev

        elif event_type == "reasoning":
            phase_name = getattr(state, "phase", state.get("phase", "") if isinstance(state, dict) else "")
            event["phase"] = phase_name
            yield event

        else:
            yield event
