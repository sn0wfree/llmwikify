"""SSE line parsing + tool-call delta accumulation.

Split from ``streamable.py`` (dual-stack merge, 2026-10-23).
``_parse_sse_line`` and ``_normalize_tool_call_ids`` share the
``tool_call_buffer`` and stay together on purpose.
"""


from __future__ import annotations

import json
from typing import Any

from .wire import _normalize_tool_call_ids


def _parse_sse_line(
    line: str,
    accumulated: str,
    tool_call_buffer: dict[int, dict],
) -> tuple[list[dict], str, dict | None] | None:
    """Parse one SSE line from an OpenAI-compatible streaming response.

    Returns:
        ``(events, new_accumulated, raw_chunk)`` when the line produces
        events, or ``None`` when the line should be skipped (blank,
        non-JSON, or an intermediate chunk with no output).

        ``raw_chunk`` is the parsed JSON dict (for callers that need
        access to fields beyond delta, e.g. ``message.content``).  It is
        ``None`` for ``[DONE]``.

        On ``finish_reason`` the events list includes the final
        ``{"type": "done", ...}`` entry; the caller should yield all
        events and then ``return``.
    """
    if not line:
        return None
    if line.startswith("data: "):
        line = line[6:]
    if line == "[DONE]":
        return ([{"type": "done", "content": accumulated}], accumulated, None)
    try:
        chunk = json.loads(line)
    except Exception:
        return None

    events: list[dict] = []
    delta = chunk.get("choices", [{}])[0].get("delta", {})

    # Reasoning / thinking
    if "reasoning_content" in delta and delta["reasoning_content"]:
        events.append({"type": "thinking", "text": delta["reasoning_content"]})

    # Content
    if "content" in delta and delta["content"]:
        accumulated += delta["content"]
        events.append({"type": "content", "text": delta["content"]})

    # Tool call accumulation by index
    if "tool_calls" in delta:
        for tc in delta["tool_calls"]:
            idx = tc.get("index", 0)
            if idx not in tool_call_buffer:
                tool_call_buffer[idx] = {
                    "id": tc.get("id", ""),
                    "name": "",
                    "args_parts": [],
                }
            entry = tool_call_buffer[idx]
            if "id" in tc and tc["id"]:
                entry["id"] = tc["id"]
            func = tc.get("function", {})
            if "name" in func and func["name"]:
                entry["name"] = func["name"]
            if "arguments" in func and func["arguments"]:
                entry["args_parts"].append(func["arguments"])

    # Finish — flush tool calls and emit done
    finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
    if finish in ("stop", "tool_calls", "length"):
        # Force locally-unique ids before yielding, since providers like
        # MiniMax have been observed emitting batch ids that share a
        # prefix or mix Anthropic/OpenAI formats — both patterns have
        # tripped the same-batch dedup logic and triggered error 2013.
        _normalize_tool_call_ids(tool_call_buffer)
        for entry in tool_call_buffer.values():
            events.append(
                {
                    "type": "tool_call",
                    "tool": entry["name"],
                    "args": "".join(entry["args_parts"]),
                    "id": entry.get("id", ""),
                }
            )
        tool_call_buffer.clear()
        events.append(
            {
                "type": "done",
                "content": accumulated,
                "finish_reason": finish,
            }
        )

    return (events, accumulated, chunk) if events else None


