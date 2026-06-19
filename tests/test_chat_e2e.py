"""End-to-end test for /api/agent/chat SSE endpoint.

This test starts a real uvicorn server, POSTs a chat message, and asserts:
1. HTTP 200 with text/event-stream content-type
2. SSE stream contains session_created, message_delta, and done events
3. LLM is actually invoked (astream_chat called)
4. Session is created in DB
5. User message and assistant response are persisted to DB

The original chat was broken because the chat loop in the legacy
service.py:253 (now archived to archive/llmwikify_v0_41_legacy/) called
asyncio.Event() without importing asyncio — returning 200 OK with
empty SSE body. The frontend parser silently dropped empty events,
so users saw "no response".

This e2e test catches that class of bug because it reads and asserts on
the actual SSE event flow, not just the HTTP status code.

Run with: pytest -m e2e
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skip(
        reason=(
            "Spawns a uvicorn subprocess loading "
            "`llmwikify.interfaces.server.core:WikiServer` as a no-arg "
            "factory, but WikiServer.__init__ requires a wiki argument. "
            "The original bug it caught (asyncio.Event without import) "
            "was in v0.41 ChatService, now archived to "
            "archive/llmwikify_v0_41_legacy/. Same SSE behaviour is "
            "covered by TestClient-based unit tests in "
            "test_apps_chat_sse.py. To re-enable: rewrite the fixture "
            "to bootstrap a Wiki in tmpdir and call "
            "`WikiServer(wiki).run(...)` directly (or use FastAPI "
            "TestClient)."
        )
    ),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
def chat_server():
    """Start a fresh llmwikify server subprocess with mock LLM.

    We use a subprocess (not in-process) to avoid AGENT_SERVICE global
    state leakage between tests. The mock LLM is a small Python module
    prepended to PYTHONPATH that monkey-patches StreamableLLMClient.
    """
    port = _free_port()
    tmpdir = tempfile.mkdtemp(prefix="chat_e2e_")
    db_dir = Path(tmpdir) / "agent"
    db_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = tmpdir  # redirect ~/.llmwikify/agent/ to tmpdir
    # Prepend mock LLM fixture + user site-packages (uvicorn is installed
    # under ~/.local/lib/python3.10/site-packages, which ``sys.executable``
    # may not have on its default sys.path).
    env["PYTHONPATH"] = (
        str(Path(__file__).parent / "_fixtures" / "mock_llm")
        + os.pathsep
        + "/home/ll/.local/lib/python3.10/site-packages"
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "llmwikify.interfaces.server.core:WikiServer",
            "--factory",
            "--host", "127.0.0.1", "--port", str(port),
            "--log-level", "warning",
        ],
        cwd="/home/ll/llmwikify",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://127.0.0.1:{port}"

    # Wait for server ready (max 15s)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=2)
                raise RuntimeError(
                    f"Server died early. stdout={out.decode()[:500]!r} "
                    f"stderr={err.decode()[:500]!r}"
                )
        time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError("Server did not become ready within 15s")

    yield base_url

    # Cleanup
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def test_chat_returns_sse_events(chat_server):
    """POST /api/agent/chat must return 200 + SSE events, not empty body.

    Regression: the legacy chat loop in service.py:253 (now archived
    to archive/llmwikify_v0_41_legacy/) called asyncio.Event() without
    importing asyncio → NameError on every request → 200 OK + empty
    body → frontend silently dropped empty events.
    """
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST",
            f"{chat_server}/api/agent/chat",
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


def test_chat_persists_messages_to_db(chat_server):
    """Chat must write user + assistant messages to chat_messages table."""
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST",
            f"{chat_server}/api/agent/chat",
            json={"message": "hello", "session_id": None, "wiki_id": None},
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    session_id = next(
        ev["session_id"] for ev in events if ev.get("type") == "session_created"
    )

    msgs_resp = client.get(
        f"{chat_server}/api/agent/sessions/{session_id}/messages"
    )
    msgs = msgs_resp.json().get("messages", [])

    assert len(msgs) >= 2, f"Expected >=2 messages, got {len(msgs)}"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["role"] == "assistant"
    assert len(msgs[1]["content"]) > 0


def test_chat_calls_llm(chat_server):
    """Chat must actually call the LLM (not silently skip).

    Verified via content match: the mock LLM yields "Hello from mock LLM!",
    so any message_delta containing that string proves the LLM was invoked.
    """
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST",
            f"{chat_server}/api/agent/chat",
            json={"message": "hello", "session_id": None, "wiki_id": None},
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    deltas = [ev for ev in events if ev.get("type") == "message_delta"]
    assert any("mock LLM" in ev.get("content", "") for ev in deltas), (
        f"No message_delta contained mock LLM content; got: {deltas}"
    )


def test_chat_handles_follow_up_message(chat_server):
    """Subsequent messages on the same session should also work."""
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST",
            f"{chat_server}/api/agent/chat",
            json={"message": "first", "session_id": None, "wiki_id": None},
        ) as resp:
            body = "".join(resp.iter_text())
    events1 = _parse_sse(body)
    session_id = next(
        ev["session_id"] for ev in events1 if ev.get("type") == "session_created"
    )

    with client.stream(
        "POST",
        f"{chat_server}/api/agent/chat",
        json={"message": "second", "session_id": session_id, "wiki_id": None},
    ) as resp:
        body = "".join(resp.iter_text())
    events2 = _parse_sse(body)
    types2 = Counter(ev.get("type") for ev in events2)
    assert "message_delta" in types2
    assert "done" in types2

    msgs_resp = client.get(
        f"{chat_server}/api/agent/sessions/{session_id}/messages"
    )
    msgs = msgs_resp.json().get("messages", [])
    assert len(msgs) >= 4  # 2 user + 2 assistant
    assert msgs[0]["content"] == "first"
    assert msgs[2]["content"] == "second"
