"""Unit tests for FastAPI routes."""

import pytest
from fastapi.testclient import TestClient

from llmwikify.server import WikiServer


@pytest.fixture
def api_client(wiki_instance):
    """Create a TestClient for the WikiServer."""
    server = WikiServer(wiki_instance, enable_webui=False)
    return TestClient(server.app)


class TestWikiRoutesStatus:
    """Tests for /api/wiki/status endpoint."""

    def test_status_endpoint(self, api_client):
        """Test status endpoint returns expected structure."""
        response = api_client.get("/api/wiki/status")
        assert response.status_code == 200
        data = response.json()
        assert "page_count" in data
        assert "total_pages" in data or "pages_by_type" in data

    def test_status_with_pages(self, api_client, wiki_instance):
        """Test status with pages in the wiki."""
        wiki_instance.write_page("TestPage", "# Test Page\n")
        response = api_client.get("/api/wiki/status")
        assert response.status_code == 200
        data = response.json()
        assert data["page_count"] >= 1


class TestWikiRoutesSearch:
    """Tests for /api/wiki/search endpoint."""

    def test_search_endpoint(self, api_client, wiki_instance):
        """Test search endpoint returns results."""
        wiki_instance.write_page("Python", "# Python\nProgramming language")
        response = api_client.get("/api/wiki/search?q=Python")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_with_limit(self, api_client, wiki_instance):
        """Test search with limit parameter."""
        for i in range(5):
            wiki_instance.write_page(f"Page{i}", f"# Page{i}\nPython content")
        response = api_client.get("/api/wiki/search?q=Python&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 2

    def test_search_empty(self, api_client):
        """Test search for non-existent term returns empty list."""
        response = api_client.get("/api/wiki/search?q=nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestWikiRoutesPage:
    """Tests for /api/wiki/page endpoints."""

    def test_read_page_exists(self, api_client, wiki_instance):
        """Test reading an existing page."""
        wiki_instance.write_page("TestPage", "# Test Page\nContent here")
        response = api_client.get("/api/wiki/page/TestPage")
        assert response.status_code == 200
        data = response.json()
        assert "content" in data or "markdown" in data

    def test_read_page_not_found(self, api_client):
        """Test reading a non-existent page returns 404."""
        response = api_client.get("/api/wiki/page/NonExistentPage")
        assert response.status_code == 404

    def test_write_page_success(self, api_client):
        """Test writing a new page."""
        response = api_client.post(
            "/api/wiki/page",
            json={"page_name": "NewPage", "content": "# New Page\n"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page_name"] == "NewPage"
        assert "message" in data

    def test_write_page_no_name(self, api_client):
        """Test writing page without page_name returns 400."""
        response = api_client.post(
            "/api/wiki/page",
            json={"content": "# No Name\n"}
        )
        assert response.status_code == 400

    def test_write_page_empty_content(self, api_client):
        """Test writing page with empty content still works."""
        response = api_client.post(
            "/api/wiki/page",
            json={"page_name": "EmptyPage", "content": ""}
        )
        assert response.status_code == 200


class TestWikiRoutesLint:
    """Tests for /api/wiki/lint endpoint."""

    def test_lint_endpoint(self, api_client):
        """Test lint endpoint returns expected structure."""
        response = api_client.get("/api/wiki/lint")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "issues" in data or "broken_links" in data or "lint" in data

    def test_lint_with_mode(self, api_client):
        """Test lint with different mode parameter."""
        response = api_client.get("/api/wiki/lint?mode=fix")
        assert response.status_code == 200

    def test_lint_with_limit(self, api_client):
        """Test lint with limit parameter."""
        response = api_client.get("/api/wiki/lint?limit=5")
        assert response.status_code == 200


class TestWikiRoutesRecommend:
    """Tests for /api/wiki/recommend endpoint."""

    def test_recommend_endpoint(self, api_client):
        """Test recommend endpoint returns expected structure."""
        response = api_client.get("/api/wiki/recommend")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict) or isinstance(data, list)


class TestWikiRoutesSink:
    """Tests for /api/wiki/sink/status endpoint."""

    def test_sink_status_endpoint(self, api_client):
        """Test sink status endpoint returns expected structure."""
        response = api_client.get("/api/wiki/sink/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestWikiRoutesGraph:
    """Tests for /api/wiki/graph endpoint."""

    def test_graph_endpoint(self, api_client):
        """Test graph endpoint returns expected structure."""
        response = api_client.get("/api/wiki/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

    def test_graph_with_current_page(self, api_client, wiki_instance):
        """Test graph with current_page parameter."""
        wiki_instance.write_page("TestPage", "# Test Page\n")
        response = api_client.get("/api/wiki/graph?current_page=TestPage")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

    def test_graph_with_mode(self, api_client):
        """Test graph with mode parameter."""
        response = api_client.get("/api/wiki/graph?mode=full")
        assert response.status_code == 200


class TestWikiRoutesGraphAnalyze:
    """Tests for /api/wiki/graph_analyze endpoint."""

    def test_graph_analyze_endpoint(self, api_client):
        """Test graph analyze endpoint returns expected structure."""
        response = api_client.get("/api/wiki/graph_analyze")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestHealthEndpoint:
    """Tests for /api/health endpoint."""

    def test_health_endpoint(self, api_client):
        """Test health check endpoint returns expected structure."""
        response = api_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "wiki" in data
        assert "features" in data
        assert "timestamp" in data

    def test_health_features(self, api_client):
        """Test health check features information."""
        response = api_client.get("/api/health")
        data = response.json()
        assert "mcp" in data["features"]
        assert "webui" in data["features"]
        assert "auth" in data["features"]
        # Agent feature is deprecated and removed
        assert "agent" not in data["features"]


class TestWikiServerConfiguration:
    """Tests for WikiServer configuration options."""

    def test_server_without_agent(self, wiki_instance):
        """Test server does not expose agent routes (agent feature deprecated)."""
        server = WikiServer(wiki_instance, enable_webui=False)
        client = TestClient(server.app)

        # Agent routes should be 404 - they are no longer registered
        response = client.get("/api/agent/status")
        assert response.status_code == 404

    def test_server_with_api_key(self, wiki_instance):
        """Test server with API key authentication."""
        server = WikiServer(wiki_instance, api_key="test-secret-key", enable_webui=False)
        client = TestClient(server.app)

        # /api/health is excluded from auth, should work without key
        response = client.get("/api/health")
        assert response.status_code == 200

        # /api/wiki/status should require authentication
        response = client.get("/api/wiki/status")
        assert response.status_code == 401

        # With correct API key, should work
        response = client.get(
            "/api/wiki/status",
            headers={"Authorization": "Bearer test-secret-key"}
        )
        assert response.status_code == 200

    def test_server_with_cors_disabled(self, wiki_instance):
        """Test server with CORS disabled."""
        server = WikiServer(
            wiki_instance,
            enable_webui=False,
            cors_enabled=False
        )
        client = TestClient(server.app)
        response = client.get("/api/health")
        # Should work without CORS
        assert response.status_code == 200
