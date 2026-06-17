"""Microcompact — replace oversized tool results with a short marker.

Borrowed from nanobot v0.2.1 runner._compact_tool_result (see
``docs/poc/nanobot-framework.md`` §2.3 for context). The marker is a
plain string so the LLM sees an obvious ``[Tool result compacted]``
banner instead of a JSON-looking blob, and the original result is
cached on the spec for caller inspection (per-run lifetime).

Default ON per the 2026-06-17 Phase A decision.
"""

from __future__ import annotations

import json
from typing import Any

from llmwikify.apps.chat.agent.spec import ChatRunSpec


def _serialize(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def microcompact_serialize(
    result: Any,
    tool_name: str,
    tool_call_id: str,
    spec: ChatRunSpec,
) -> tuple[str, bool, int]:
    """Return ``(content_str, was_compacted, chars_saved)``.

    ``chars_saved`` is only meaningful when ``was_compacted`` is True
    and represents the byte reduction vs. shipping the original.
    """
    result_str = _serialize(result)

    if not spec.microcompact:
        return result_str, False, 0
    if tool_name not in spec.microcompact_compactable_tools:
        return result_str, False, 0
    if len(result_str) <= spec.microcompact_keep_chars:
        return result_str, False, 0

    spec._compacted_results[tool_call_id] = result
    head = result_str[: spec.microcompact_keep_chars]
    marker = (
        f"[Tool result compacted]\n"
        f"Tool: {tool_name}\n"
        f"Original: {len(result_str)} chars\n"
        f"Kept: {spec.microcompact_keep_chars} chars (head)\n"
        f"tool_call_id: {tool_call_id}\n\n"
        f"{head}"
    )
    saved = len(result_str) - len(marker)
    return marker, True, max(saved, 0)


def build_microcompact_fn(
    spec: ChatRunSpec,
    counter: dict[str, int] | None = None,
) -> Any:
    """Build a closure suitable for ``ChatReActBridge(microcompact_fn=...)``.

    The returned callable has the signature
    ``(result, tool_name, call_id) -> tuple[str, bool, int]`` matching
    :func:`microcompact_serialize`. The optional ``counter`` dict is
    updated in place so callers can aggregate microcompact stats.
    """
    def _fn(
        result: Any, tool_name: str, call_id: str,
    ) -> tuple[str, bool, int]:
        content, compacted, saved = microcompact_serialize(
            result, tool_name, call_id, spec,
        )
        if compacted and counter is not None:
            counter["count"] = counter.get("count", 0) + 1
            counter["chars_saved"] = counter.get("chars_saved", 0) + saved
        return content, compacted, saved

    return _fn
