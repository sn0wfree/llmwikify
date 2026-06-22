"""Chat v2 persistence helpers (Plan B B-4).

Pure functions extracted from ``ChatOrchestrator._chat_via_runner_v2``
so the orchestrator's chat() flow stays declarative and the
persistence + extraction logic can be tested in isolation.

  - ``save_assistant_done_message``: persist the assistant message
    on the V2 ``done`` event, counting tokens + binding research_run_id.
  - ``extract_research_run_id_from_tools``: scan tool_call_end events
    for an autoresearch ``run_id`` so the assistant message can be
    bound to the run (frontend reload reconstructs the card).

Public surface kept thin: two free functions, no state. The
orchestrator keeps 1-line shim methods (``_save_assistant_message_v2``
/ ``_extract_research_run_id_from_tools``) so existing test imports
continue to work unchanged.
"""

from __future__ import annotations

from typing import Any

from llmwikify.foundation.llm.token_estimator import count_tokens


def save_assistant_done_message(
    tool_executor: Any,
    session_id: str,
    content: str,
    tool_calls: list[dict],
    research_run_id: str | None,
) -> None:
    """Save assistant message to DB on done (V2 path).

    Counts tokens (no model name fallback per LAL/audit fix),
    attaches research_run_id for /study autoresearch integration,
    persists via ``tool_executor.save_message``.

    Args:
        tool_executor: duck-typed executor with ``save_message``.
        session_id: chat session id (single source of truth for binding).
        content: final assistant message text.
        tool_calls: accumulated tool calls for the turn (may be empty).
        research_run_id: optional autoresearch run_id to bind.
    """
    tokens_output = count_tokens(content, "unknown")
    tool_executor.save_message(
        session_id,
        "assistant",
        content,
        tool_calls=tool_calls or None,
        tokens_output=tokens_output,
        research_run_id=research_run_id,
    )


def extract_research_run_id_from_tools(
    tool_calls: list[dict],
) -> str | None:
    """Scan tool_call_end events for an autoresearch run_id.

    When /study triggers ``autoresearch_compound_run``, extracts its
    ``run_id`` from the tool result so the assistant message can be
    bound to the run (frontend reload reconstructs the card).

    Handles both SkillResult envelope (``status == "ok"``, nested under
    ``data``) and bare result dicts. Returns the first non-empty
    string run_id found, or ``None`` if no autoresearch tool fired.
    """
    for tc in tool_calls:
        name = tc.get("tool", "")
        if "autoresearch_compound" not in name or "run" not in name:
            continue
        result = tc.get("result")
        if not isinstance(result, dict):
            continue
        data = result.get("data") if result.get("status") == "ok" else result
        if not isinstance(data, dict):
            continue
        run_id = data.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


__all__ = [
    "save_assistant_done_message",
    "extract_research_run_id_from_tools",
]
