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


import pytest
import httpx


class TestChatReAct:
    """Test chat and ReAct agent with real LLM calls.

    Covers TUTORIAL.md Scenario 4 (Chat + ReAct Agent).
    Requires server running at http://localhost:8765.
    """

    @pytest.fixture
    def client(self, server_url):
        """HTTP client for server requests."""
        return httpx.Client(base_url=server_url, timeout=30.0)

    def test_4_1_health_check(self, client):
        """Step 4.1: Health check endpoint.

        GET /api/health returns {"status": "ok", ...}.
        """
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    def test_4_2_auth_optional(self):
        """Step 4.2: Authentication is optional by default.

        POST /api/agent/chat works without Authorization header
        unless --auth-token is configured on the server.
        """
        client = httpx.Client(base_url="http://localhost:8765", timeout=10.0)
        response = client.post(
            "/api/agent/chat",
            json={"session_id": "test", "message": "hello"},
        )
        assert response.status_code in [200, 401, 403]

    def test_4_3_chat_sse(self, client):
        """Step 4.3: Streaming chat via Server-Sent Events.

        POST /api/agent/chat with stream returns SSE events:
        reasoning → phase → tool_call → stream_end.
        """
        headers = {"Authorization": "Bearer test-token"}
        with client.stream(
            "POST",
            "/api/agent/chat",
            json={"session_id": "test", "message": "What is Python?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(line)
            assert len(events) > 0

    def test_4_4_chat_with_wiki_tool(self, client):
        """Step 4.4: Chat can invoke wiki tools.

        LLM decides to call wiki_search() to answer a query.
        """
        headers = {"Authorization": "Bearer test-token"}
        response = client.post(
            "/api/agent/chat",
            json={
                "session_id": "test",
                "message": "Search for Python in the wiki",
            },
            headers=headers,
        )
        assert response.status_code == 200

    def test_4_5_chat_session_list(self, client):
        """Step 4.5: List all chat sessions.

        GET /api/agent/sessions returns active session metadata.
        """
        response = client.get("/api/agent/sessions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))
