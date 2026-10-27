"""OpenAI-compatible request wire-format helpers.

Split from ``streamable.py`` (dual-stack merge, 2026-10-23):
thinking extra_body, role alternation, tool-call id normalization,
and pre-flight request validation.
"""


from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# ─── Thinking style map (borrowed from nanobot OpenAICompatProvider) ───
#
# Different OpenAI-compatible providers expose their "thinking on/off"
# toggle under different keys:
#
#   reasoning_split:    {"reasoning_split": true|false}             (MiniMax)
#   thinking_type:      {"thinking": {"type": "enabled"|"disabled"}} (DeepSeek,
#                                                                  VolcEngine,
#                                                                  Xiaomi MiMo)
#   enable_thinking:    {"enable_thinking": true|false}             (DashScope/Qwen)
#
# Borrowed from nanobot v0.2.1 providers/openai_compat_provider.py:73-77
# (openai_compat_provider._THINKING_STYLE_MAP). Decouples the wire format
# from per-provider code so new providers can register a new style without
# touching call sites.

_THINKING_STYLE_BUILDERS: dict[str, Any] = {
    "thinking_type": lambda on: {"thinking": {"type": "enabled" if on else "disabled"}},
    "enable_thinking": lambda on: {"enable_thinking": on},
    "reasoning_split": lambda on: {"reasoning_split": on},
}


def build_thinking_extra_body(
    style: str,
    thinking_enabled: bool,
) -> dict[str, Any] | None:
    """Build the provider-native ``extra_body`` snippet for a thinking style.

    Returns the dict to merge into the chat-completions request body,
    or None if *style* is unknown (e.g. empty string for providers
    that don't support a thinking toggle).
    """
    builder = _THINKING_STYLE_BUILDERS.get(style)
    return builder(thinking_enabled) if builder else None



# ─── Role alternation hardening (borrowed from nanobot base.py) ───
#
# Some OpenAI-compatible gateways reject requests where the last
# message is ``assistant`` (no prefill support) or where two
# consecutive non-system messages share the same role.
#
# Borrowed from nanobot v0.2.1 providers/base.py:396-463
# (``LLMProvider._enforce_role_alternation``), simplified to the
# behaviour we actually need: drop trailing assistant messages,
# recover by promoting the last popped assistant to ``user`` so
# the LLM can still see it.
#
# Mutates the input list in-place and returns it for chaining.


def _enforce_role_alternation(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize role alternation for OpenAI-compatible APIs.

    - Merges consecutive same-role user/assistant messages by
      concatenating their string content.
    - Drops trailing assistant messages without tool_calls (no prefill support).
    - Preserves trailing assistant messages with tool_calls (needed for tool dispatch).
    - Recovers by promoting the last dropped assistant to ``user``
      so the LLM still sees its content.
    - Inserts a synthetic user message if the first non-system
      message is a bare assistant (prevents some providers from
      rejecting the request).

    Mutates *messages* in-place and returns it.
    """
    if not messages:
        return messages

    merged: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if (
            merged
            and role not in (None, "system", "tool")
            and merged[-1].get("role") == role
            and role in ("user", "assistant")
        ):
            prev = merged[-1]
            if role == "assistant":
                prev_has_tools = bool(prev.get("tool_calls"))
                curr_has_tools = bool(msg.get("tool_calls"))
                if curr_has_tools:
                    merged[-1] = dict(msg)
                    continue
                if prev_has_tools:
                    continue
            prev_content = prev.get("content") or ""
            curr_content = msg.get("content") or ""
            if isinstance(prev_content, str) and isinstance(curr_content, str):
                prev["content"] = (prev_content + "\n\n" + curr_content).strip()
            else:
                merged[-1] = dict(msg)
        else:
            merged.append(dict(msg))

    last_popped: dict[str, Any] | None = None
    while merged and merged[-1].get("role") == "assistant":
        if merged[-1].get("tool_calls"):
            break  # Don't pop assistant messages with tool_calls
        last_popped = merged.pop()

    if (
        merged
        and last_popped is not None
        and not any(m.get("role") in ("user", "tool") for m in merged)
    ):
        recovered = dict(last_popped)
        recovered["role"] = "user"
        merged.append(recovered)

    # Drop leading orphan tool messages (those whose declaring
    # assistant+tool_calls isn't preserved in the kept window).
    # Walks past leading ``system`` first, then strips any tool at
    # the front that has no preceding assistant+tool_calls in the
    # original ``messages`` sequence that declared its tool_call_id.
    # Without this, a recovered (truncate-cut) tool with no surviving
    # owner would be sent to the provider and trigger error 2013.
    i = 0
    while i < len(merged) and merged[i].get("role") == "system":
        i += 1
    while i < len(merged) and merged[i].get("role") == "tool":
        target_id = merged[i].get("tool_call_id", "")
        owner_found = False
        for orig in messages:
            if orig is merged[i]:
                break
            tcs = orig.get("tool_calls") if orig.get("role") == "assistant" else None
            if tcs and any(tc.get("id") == target_id for tc in tcs):
                owner_found = True
                break
        if owner_found:
            break
        del merged[i]

    # Safety net: first non-system message must not be bare assistant.
    for i, msg in enumerate(merged):
        if msg.get("role") != "system":
            if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                merged.insert(
                    i, {"role": "user", "content": "(conversation continued)"}
                )
            break

    messages[:] = merged
    return messages



def _normalize_tool_call_ids(tool_call_buffer: dict[int, dict[str, Any]]) -> None:
    """Force provider tool_call IDs to locally generated 24-hex UUIDs in-place.

    Defends against MiniMax-side quirks observed in d8a24ecf / error 2013:
      - prefix-based dedup when batch IDs share a nanosecond-counter prefix
      - mixed-format returns (Anthropic ``call_function_*_<seq>`` alongside
        OpenAI-style ``call_<24hex>`` in the same batch)
      - empty IDs from text-mode or older streamable paths

    Each entry's ``id`` field is overwritten with a fresh
    ``call_<24hex>`` whenever the existing value is missing, malformed,
    or already seen within this batch.
    """
    seen: set[str] = set()
    for entry in tool_call_buffer.values():
        cid = entry.get("id", "") or ""
        if not cid.startswith("call_") or cid in seen:
            entry["id"] = f"call_{uuid.uuid4().hex[:24]}"
        else:
            seen.add(cid)



def _validate_request(
    messages: list[dict[str, Any]] | None,
    generation_params: dict[str, Any] | None = None,
) -> None:
    """Pre-flight validation for chat completion requests.

    Catches the most common provider-side rejections *before* they
    cost a network round-trip:

      - Empty ``messages`` (MiniMax error 2013)
      - ``top_p`` outside the OpenAI-compatible (0, 1] range
      - ``temperature`` outside [0, 2] (Anthropic-compatible ceiling)

    Also mutates *messages* in-place via :func:`_enforce_role_alternation`
    so trailing assistant messages and bare-assistant-leading requests
    get normalized before the network round-trip (borrowed from
    nanobot base.py: prevents GLM-style error 1214 and similar).

    Provider-specific quirks (e.g. MiniMax reasoning_split + tools
    combinations) are not validated here — they will surface as
    ``LLMRequestError`` with the full body, which is informative
    enough to diagnose.
    """
    if not messages:
        raise ValueError(
            "messages must be a non-empty list of role/content dicts; "
            "got empty list. Add at least one system or user message "
            "before calling the LLM."
        )
    params = generation_params or {}
    if "top_p" in params:
        top_p = params["top_p"]
        if not isinstance(top_p, (int, float)) or not (0.0 < top_p <= 1.0):
            raise ValueError(f"top_p must be a number in (0, 1]; got {top_p!r}")
    if "temperature" in params:
        temp = params["temperature"]
        if not isinstance(temp, (int, float)) or not (0.0 <= temp <= 2.0):
            raise ValueError(f"temperature must be a number in [0, 2]; got {temp!r}")
    _enforce_role_alternation(messages)
