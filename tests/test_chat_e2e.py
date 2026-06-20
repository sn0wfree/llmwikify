"""End-to-end test for /api/agent/chat SSE endpoint.

Runs the chat endpoint in-process via FastAPI TestClient against a
fresh ``WikiServer`` wired with the minimal mock LLM fixture
(``tests/_fixtures/mock_llm/``) — no real provider, no uvicorn
subprocess. Catches the original v0.41 regression where
``service.py:253`` (now archived to ``archive/llmwikify_v0_41_legacy/``)
called ``asyncio.Event()`` without importing asyncio → 200 OK with
empty SSE body.

Phase A-3 (2026-06-20): rewrote the original subprocess fixture
(which couldn't bootstrap ``WikiServer`` as a no-arg uvicorn
factory) into an in-process TestClient + mock LLM. Same SSE
behaviour is now reproducible without spawning a server.

Run with: ``pytest tests/test_chat_e2e.py`` (no markers needed).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "_fixtures"
if str(_FIXTURES_DIR) not in sys.path:
    sys.path.insert(0, str(_FIXTURES_DIR))


def _parse_sse(body: str) -> list[dict]:
    """Parse SSE response body into a list of event dicts."""
    events: list[dict] = []
    for line in body.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            events.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            pass
    return events


@pytest.fixture
def chat_client(tmp_path, monkeypatch):
    """Spin up a WikiServer in tmpdir with mock LLM + minimal wiki.

    Yields a fastapi.testclient.TestClient pointed at the app so
    tests can POST /api/agent/chat synchronously and parse SSE.
    The mock LLM is installed at module import time
    (``mock_llm.__init__.py`` does ``install()`` when first
    imported); sys.path is patched in the body of this fixture
    so the import happens before ``WikiServer`` builds its app.

    The wiki_service._llm slot is monkeypatched to a MagicMock
    provider — this short-circuits ``agent_service._get_llm()`` /
    ``wiki_service.get_llm()`` and prevents MiniMax API key lookup
    during route registration.
    """
    from unittest.mock import MagicMock

    import mock_llm  # noqa: F401  -- triggers install()
    from fastapi.testclient import TestClient

    from llmwikify.interfaces.server.core import WikiServer
    from llmwikify.kernel import Wiki

    wiki = Wiki(tmp_path / "wiki")
    wiki.init()
    monkeypatch.setenv("HOME", str(tmp_path))
    mock_provider = MagicMock()
    # Provide an async astream_chat so the chat loop can stream
    # something instead of hitting the real provider.
    async def _fake_astream(*args, **kwargs):
        yield {"type": "content", "text": "Hello from mock LLM!"}
        yield {"type": "done", "content": "Hello from mock LLM!"}
    mock_provider.astream_chat = _fake_astream
    monkeypatch.setattr(
        "llmwikify.apps.wiki.service.WikiService.get_llm",
        lambda self: mock_provider,
    )
    server = WikiServer(
        wiki,
        provider=mock_provider,
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_webui=False,
    )
    with TestClient(server.app) as client:
        yield client


def test_chat_returns_sse_events(chat_client):
    """POST /api/agent/chat must return 200 + SSE events, not empty body."""
    with chat_client.stream(
        "POST",
        "/api/agent/chat",
        json={"message": "hello", "session_id": None, "wiki_id": None},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = "".join(resp.iter_text())

    events = _parse_sse(body)
    assert len(events) > 0, "SSE body was empty — chat produced no events"

    types = Counter(ev.get("type") for ev in events)
    assert "session_created" in types
    assert "message_delta" in types, f"No message_delta in {dict(types)}"
    assert "done" in types, f"No done in {dict(types)}"


def test_chat_persists_messages_to_db(chat_client):
    """Chat must write user + assistant messages to chat_messages table.

    The default ``get_chat_messages`` ordering is newest-first, so we
    don't assume a specific position — just that both messages exist.
    """
    with chat_client.stream(
        "POST",
        "/api/agent/chat",
        json={"message": "hello", "session_id": None, "wiki_id": None},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _parse_sse(body)
    session_id = next(
        ev["session_id"] for ev in events if ev.get("type") == "session_created"
    )

    msgs_resp = chat_client.get(
        f"/api/agent/sessions/{session_id}/messages"
    )
    msgs = msgs_resp.json().get("messages", [])

    assert len(msgs) >= 2, f"Expected >=2 messages, got {len(msgs)}"
    roles = {m["role"] for m in msgs}
    assert "user" in roles, f"Expected user role in messages, got {roles}"
    assert "assistant" in roles, f"Expected assistant role in messages, got {roles}"
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert user_msg["content"] == "hello"
    asst_msg = next(m for m in msgs if m["role"] == "assistant")
    assert len(asst_msg["content"]) > 0


def test_chat_calls_llm(chat_client):
    """Chat must actually call the LLM (not silently skip).

    The mock LLM yields "Hello from mock LLM!", so any
    message_delta containing that string proves the LLM was
    invoked.
    """
    with chat_client.stream(
        "POST",
        "/api/agent/chat",
        json={"message": "hello", "session_id": None, "wiki_id": None},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _parse_sse(body)
    deltas = [ev for ev in events if ev.get("type") == "message_delta"]
    assert any("mock LLM" in ev.get("content", "") for ev in deltas), (
        f"No message_delta contained mock LLM content; got: {deltas}"
    )


def test_chat_handles_follow_up_message(chat_client):
    """Subsequent messages on the same session should also work."""
    with chat_client.stream(
        "POST",
        "/api/agent/chat",
        json={"message": "first", "session_id": None, "wiki_id": None},
    ) as resp:
        body = "".join(resp.iter_text())
    events1 = _parse_sse(body)
    session_id = next(
        ev["session_id"] for ev in events1 if ev.get("type") == "session_created"
    )

    with chat_client.stream(
        "POST",
        "/api/agent/chat",
        json={"message": "second", "session_id": session_id, "wiki_id": None},
    ) as resp:
        body = "".join(resp.iter_text())
    events2 = _parse_sse(body)
    types2 = Counter(ev.get("type") for ev in events2)
    assert "message_delta" in types2
    assert "done" in types2

    msgs_resp = chat_client.get(
        f"/api/agent/sessions/{session_id}/messages"
    )
    msgs = msgs_resp.json().get("messages", [])
    assert len(msgs) >= 4  # 2 user + 2 assistant
    contents = [m["content"] for m in msgs if m["role"] == "user"]
    assert "first" in contents
    assert "second" in contents
