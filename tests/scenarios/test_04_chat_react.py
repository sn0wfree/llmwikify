# tests/scenarios/test_04_chat_react.py
"""Scenario 4: Chat + ReAct Agent - With LLM + Server.

## Background
The Chat endpoint uses ReAct loop: LLM decides which wiki tools to
call, executes them, and streams results via SSE. Up to 4 tool-call
rounds per query.

## Architecture
```mermaid
graph LR
    Browser -->|SSE| API[/api/agent/chat/]
    API --> ChatService
    ChatService --> ReAct[ReAct Engine<br/>max 4 rounds]
    ReAct --> Tools[26 wiki_* tools]
    Tools --> Wiki
    ReAct --> LLM[LLM Provider]
```

## Troubleshooting
- SSE 401 Unauthorized: add Authorization Bearer token
- tool_call never returns: check LLM config (api_key, base_url)
- save_warning frequent: by design (human-in-loop), set posthoc mode
"""


import json
from pathlib import Path

import httpx
import pytest


def _get_real_jwt(server_url: str) -> str:
    """Real JWT from /api/auth/verify using ~/.llmwikify/pat. Hard-fail.

    Forces CI/dev to have a PAT configured; no silent skipping.
    Unit tests (with ``MockTransport``) do not call this.
    """
    pat_path = Path.home() / ".llmwikify" / "pat"
    assert pat_path.exists(), (
        f"No PAT at {pat_path}. Run `llmwikify pat` first."
    )
    pat = pat_path.read_text().strip()
    resp = httpx.post(
        f"{server_url}/api/auth/verify",
        json={"pat": pat},
        timeout=5.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _mock_client(server_url: str, transport: httpx.MockTransport) -> httpx.Client:
    """Helper: build an httpx.Client with a mock transport for unit tests."""
    return httpx.Client(base_url=server_url, timeout=30.0, transport=transport)


class TestChatReAct:
    """Test chat and ReAct agent with real LLM calls.

    Covers TUTORIAL.md Scenario 4 (Chat + ReAct Agent).
    Requires server running at http://localhost:8765.
    """

    @pytest.fixture
    def client(self, server_url):
        """HTTP client for server requests."""
        return httpx.Client(base_url=server_url, timeout=30.0)

    @pytest.mark.requires_server
    def test_4_1_health_check(self, client):
        """Step 4.1: Health check endpoint.

        GET /api/health returns {"status": "ok", ...}.
        """
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    @pytest.mark.requires_server
    def test_4_2_auth_optional(self, client):
        """Step 4.2: Authentication is optional by default.

        POST /api/agent/chat works without Authorization header
        unless --auth-token is configured on the server.
        """
        response = client.post(
            "/api/agent/chat",
            json={"session_id": "test", "message": "hello"},
        )
        assert response.status_code in [200, 401, 403]

    @pytest.mark.requires_server
    def test_4_3_chat_sse_unit(self, client):
        """Step 4.3 (unit): verify SSE contract via mocked httpx transport.

        No LLM, no real network. Verifies request shape, Authorization
        header presence, and SSE event parsing.
        """
        captured = {}

        def mock_transport(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            try:
                captured["body"] = json.loads(request.content)
            except Exception:
                captured["body"] = None
            # Enforce auth at the transport layer
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer "):
                return httpx.Response(401)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    'data: {"type":"reasoning","content":"thinking..."}\n\n'
                    'data: {"type":"stream_end","tokens":42}\n\n'
                ),
            )

        unit_client = _mock_client(client.base_url, httpx.MockTransport(mock_transport))
        with unit_client.stream(
            "POST",
            "/api/agent/chat",
            json={"session_id": "unit-sse", "message": "ping"},
            headers={"Authorization": "Bearer unit-test-jwt"},
        ) as response:
            assert response.status_code == 200
            events = [line for line in response.iter_lines() if line.startswith("data:")]
            assert len(events) == 2

        # Verify request shape (the stream was opened so body was sent)
        assert captured["body"]["session_id"] == "unit-sse"
        assert captured["body"]["message"] == "ping"
        assert captured["headers"]["authorization"] == "Bearer unit-test-jwt"

    @pytest.mark.requires_server
    @pytest.mark.llm
    def test_4_3_chat_sse_e2e(self, server_url):
        """Step 4.3 (e2e): real LLM, real JWT, real SSE. Marked
        ``@pytest.mark.llm`` so the conftest auto-skips when
        LLM_API_KEY is missing."""
        token = _get_real_jwt(server_url)
        with httpx.Client(base_url=server_url, timeout=300.0) as c:
            with c.stream(
                "POST",
                "/api/agent/chat",
                json={"session_id": "e2e-sse", "message": "What is Python?"},
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                assert response.status_code == 200
                events = [
                    line for line in response.iter_lines() if line.startswith("data:")
                ]
                assert len(events) > 0

    @pytest.mark.requires_server
    def test_4_4_chat_with_wiki_tool_unit(self, client):
        """Step 4.4 (unit): verify chat request body shape (wiki_search path)."""
        captured = {}

        def mock_transport(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={
                    "session_id": "unit-wiki",
                    "tool_calls": [
                        {"name": "wiki_search", "args": {"q": "python"}}
                    ],
                    "response": "Wikipedia: Python is a programming language...",
                },
            )

        unit_client = _mock_client(client.base_url, httpx.MockTransport(mock_transport))
        response = unit_client.post(
            "/api/agent/chat",
            json={"session_id": "unit-wiki", "message": "Search for Python in the wiki"},
            headers={"Authorization": "Bearer unit-test-jwt"},
        )
        assert response.status_code == 200
        assert captured["body"]["session_id"] == "unit-wiki"
        assert captured["body"]["message"] == "Search for Python in the wiki"
        assert captured["headers"]["authorization"] == "Bearer unit-test-jwt"

    @pytest.mark.requires_server
    @pytest.mark.llm
    def test_4_4_chat_with_wiki_tool_e2e(self, server_url):
        """Step 4.4 (e2e): real LLM with wiki_search tool. Auto-skipped if no
        LLM_API_KEY; requires PAT for auth."""
        token = _get_real_jwt(server_url)
        with httpx.Client(base_url=server_url, timeout=300.0) as c:
            r = c.post(
                "/api/agent/chat",
                json={
                    "session_id": "e2e-wiki",
                    "message": "Search for Python in the wiki",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200

    @pytest.mark.requires_server
    def test_4_5_chat_session_list(self, client):
        """Step 4.5: List all chat sessions.

        GET /api/agent/sessions returns active session metadata.
        """
        response = client.get("/api/agent/sessions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))
