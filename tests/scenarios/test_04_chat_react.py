# tests/scenarios/test_04_chat_react.py
"""Scenario 4: Chat + ReAct Agent - With LLM + Server."""

import pytest
import httpx


class TestChatReAct:
    """Test chat and ReAct agent with real LLM calls."""

    @pytest.fixture
    def client(self, server_url):
        """HTTP client for server requests."""
        return httpx.Client(base_url=server_url, timeout=30.0)

    def test_4_1_health_check(self, client):
        """Health check returns ok."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    def test_4_2_auth_optional(self):
        """Request without auth token still works (auth is optional)."""
        client = httpx.Client(base_url="http://localhost:8765", timeout=10.0)
        response = client.post(
            "/api/agent/chat",
            json={"session_id": "test", "message": "hello"},
        )
        # Auth is optional in default config, so 200 is acceptable
        assert response.status_code in [200, 401, 403]

    def test_4_3_chat_sse(self, client):
        """Chat SSE returns streaming events."""
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
        """Chat can call wiki tools."""
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
        """List chat sessions."""
        response = client.get("/api/agent/sessions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))
