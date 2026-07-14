"""Tests for translate_react_events terminal event handling.

Covers the bug where a `phase: done` event with no `reason` field
(max_rounds exhausted) was silently dropped by the bridge, causing
the research loop to appear stuck with no terminal event.
"""

from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.agent.research_bridge import translate_react_events


def _make_state(**overrides):
    """Minimal mock state object with get-attr and get-item access."""
    data = {"round": 4, "max_rounds": 15, "phase": "synthesizing", **overrides}
    return type("State", (), {
        "__getattr__": lambda self, k: data.get(k, 0),
        "__getitem__": lambda self, k: data[k],
        "get": lambda self, k, d=None: data.get(k, d),
    })()


async def _collect(ait):
    """Consume an async iterator into a list."""
    return [ev async for ev in ait]


async def _aiter(items):
    """Wrap a list into an async iterator."""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_phase_done_no_reason_yields_round_max():
    """When ReactLoop exhausts max_rounds, it yields phase: done with no
    reason field. The bridge must yield a round_max event (not silence)."""
    state = _make_state()
    events = [{"type": "phase", "phase": "done", "final_state": {}}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
        )
    )
    assert len(result) == 1
    assert result[0]["type"] == "round_max"
    assert "15" in result[0]["message"]


@pytest.mark.asyncio
async def test_phase_done_reason_max_rounds_yields_round_max():
    """Explicit reason='max_rounds' (if ReactLoop adds it later)."""
    state = _make_state()
    events = [{"type": "phase", "phase": "done", "reason": "max_rounds"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
        )
    )
    assert len(result) == 1
    assert result[0]["type"] == "round_max"


@pytest.mark.asyncio
async def test_phase_done_reason_returned_done_no_handler():
    """reason_returned_done without action_done_handler yields completed."""
    state = _make_state(phase="reporting")
    events = [{"type": "phase", "phase": "done", "reason": "reason_returned_done"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
        )
    )
    assert len(result) == 1
    assert result[0]["type"] == "completed"
    assert result[0]["phase"] == "reporting"


@pytest.mark.asyncio
async def test_phase_done_reason_returned_done_with_handler():
    """reason_returned_done with action_done_handler calls the handler."""
    state = _make_state(phase="done")

    async def handler(s):
        yield {"type": "report_saved", "ok": True}

    events = [{"type": "phase", "phase": "done", "reason": "reason_returned_done"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
            action_done_handler=handler,
        )
    )
    assert len(result) == 1
    assert result[0]["type"] == "report_saved"


@pytest.mark.asyncio
async def test_phase_cancelled():
    state = _make_state(phase="analyzing")
    events = [{"type": "phase", "phase": "cancelled"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
        )
    )
    assert result[0]["type"] == "cancelled"


@pytest.mark.asyncio
async def test_phase_timeout():
    state = _make_state()
    events = [{"type": "phase", "phase": "timeout"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=300,
            update_status=lambda *a: None,
        )
    )
    assert result[0]["type"] == "error"
    assert "300" in result[0]["error"]


@pytest.mark.asyncio
async def test_reasoning_event_gets_phase():
    state = _make_state(phase="gathering")
    events = [{"type": "reasoning", "thought": "need more", "action": "gather"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
        )
    )
    assert result[0]["phase"] == "gathering"


@pytest.mark.asyncio
async def test_round_complete_passthrough():
    state = _make_state()
    events = [{"type": "round_complete", "round": 3, "action": "analyze"}]
    result = await _collect(
        translate_react_events(
            _aiter(events),
            state=state,
            session_id="s1",
            timeout_seconds=60,
            update_status=lambda *a: None,
        )
    )
    assert result[0]["type"] == "round_complete"
