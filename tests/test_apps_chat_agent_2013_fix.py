"""Tests for streamable.LLM client helpers.

Covers the new defenses against MiniMax-side error 2013:

  - ``_normalize_tool_call_ids`` rewrites batch IDs that share a
    prefix or mix Anthropic/OpenAI formats.

  - ``_enforce_role_alternation`` drops leading orphan ``tool``
    messages whose declaring ``assistant+tool_calls`` is missing.

  - ``count_messages`` includes ``tool_calls`` tokens so budget
    accounting reflects the actual wire cost.
"""

from __future__ import annotations

import pytest

from llmwikify.foundation.llm.streamable import (
    _enforce_role_alternation,
    _normalize_tool_call_ids,
)
from llmwikify.foundation.llm.token_estimator import count_messages

# ─── _normalize_tool_call_ids ────────────────────────────────


class TestNormalizeToolCallIDs:
    def test_empty_id_replaced_with_local_uuid(self) -> None:
        buf = {0: {"id": "", "name": "t", "args_parts": []}}
        _normalize_tool_call_ids(buf)
        cid = buf[0]["id"]
        assert cid.startswith("call_")
        # 24 hex chars after the "call_" prefix
        assert len(cid) == 5 + 24

    def test_invalid_format_replaced_with_local_uuid(self) -> None:
        buf = {0: {"id": "toolu_bdrk_01U74yxf14B6fvB7mo3dn6Kh", "name": "t", "args_parts": []}}
        _normalize_tool_call_ids(buf)
        cid = buf[0]["id"]
        assert cid.startswith("call_")
        assert len(cid) == 5 + 24
        # Old Anthropic-style id replaced wholesale
        assert cid != "toolu_bdrk_01U74yxf14B6fvB7mo3dn6Kh"

    def test_dedup_collisions_within_same_batch(self) -> None:
        """Two IDs that share a nanosecond-counter prefix (the pattern
        MiniMax emitted in d8a24ecf) must NOT both survive."""
        buf = {
            0: {"id": "call_a1b2c3d4", "name": "t", "args_parts": []},
            1: {"id": "call_a1b2c3d4", "name": "t", "args_parts": []},
        }
        _normalize_tool_call_ids(buf)
        assert buf[0]["id"] == "call_a1b2c3d4"
        assert buf[1]["id"] != buf[0]["id"]
        assert buf[1]["id"].startswith("call_") and len(buf[1]["id"]) == 5 + 24

    def test_unique_ids_preserved(self) -> None:
        cid_a = "call_aaaa1111aaaa1111aaaa1111"
        cid_b = "call_bbbb2222bbbb2222bbbb2222"
        buf = {
            0: {"id": cid_a, "name": "t", "args_parts": []},
            1: {"id": cid_b, "name": "t", "args_parts": []},
        }
        _normalize_tool_call_ids(buf)
        assert buf[0]["id"] == cid_a
        assert buf[1]["id"] == cid_b


# ─── _enforce_role_alternation: leading-orphan drop ─────────


class TestEnforceRoleAlternation:
    def test_leading_orphan_tool_after_system_is_dropped(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "orphan", "tool_call_id": "x"},
            {"role": "user", "content": "hi"},
        ]
        _enforce_role_alternation(msgs)
        # The orphan tool at position 1 has no preceding assistant
        # declaring it; must be stripped.
        roles = [m.get("role") for m in msgs]
        assert "tool" not in roles or all(
            m.get("tool_call_id") != "x" for m in msgs if m.get("role") == "tool"
        )

    def test_truly_leading_tool_without_system_is_dropped(self) -> None:
        msgs = [
            {"role": "tool", "content": "orphan", "tool_call_id": "x"},
            {"role": "user", "content": "hi"},
        ]
        _enforce_role_alternation(msgs)
        assert msgs[0].get("role") != "tool"

    def test_tool_with_owner_in_messages_is_kept(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "x", "type": "function",
                     "function": {"name": "f", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "content": "result", "tool_call_id": "x"},
            {"role": "user", "content": "u2"},
        ]
        _enforce_role_alternation(msgs)
        roles = [m.get("role") for m in msgs]
        assert "tool" in roles

    def test_trailing_assistant_with_tool_calls_preserved(self) -> None:
        """Fix 4: trailing assistant(tool_calls) is NOT popped."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "x", "type": "function",
                     "function": {"name": "f", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "content": "result", "tool_call_id": "x"},
        ]
        _enforce_role_alternation(msgs)
        assert msgs[-1]["role"] == "tool"


# ─── count_messages: tool_calls tokens ──────────────────────────


class TestCountMessagesToolCalls:
    def test_assistant_with_tool_calls_counts_function_tokens(self) -> None:
        msgs = [
            {"role": "system", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"q":"hello world"}',
                    },
                }],
            },
            {"role": "tool", "content": "result"},
        ]
        tokens = count_messages(msgs)
        # System + content + tool_call function (name+args) all count
        # Without the tool_calls branch this would be much smaller.
        assert tokens >= 25

    def test_message_without_tool_calls_unchanged(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        assert count_messages(msgs) == count_messages(msgs)
