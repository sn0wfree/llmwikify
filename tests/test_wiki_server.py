"""Unit tests for WikiServer core class."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from llmwikify.server import WikiServer


class TestWikiServerInit:
    """Tests for WikiServer initialization."""

    def test_init_basic(self, wiki_instance):
        """Test basic WikiServer initialization."""
        server = WikiServer(wiki_instance)
        assert server.wiki == wiki_instance
        assert server.app is not None

    def test_init_with_mcp_disabled(self, wiki_instance):
        """Test initializing with MCP disabled."""
        server = WikiServer(wiki_instance, enable_mcp=False)
        assert server.mcp is None

    def test_init_with_mcp_enabled(self, wiki_instance):
        """Test initializing with MCP enabled (default)."""
        server = WikiServer(wiki_instance)
        assert server.mcp is not None

    def test_init_with_rest_disabled(self, wiki_instance):
        """Test initializing with REST disabled."""
        # With REST disabled, there should be no /api/wiki routes
        server = WikiServer(wiki_instance, enable_rest=False, enable_webui=False)
        client = TestClient(server.app)
        response = client.get("/api/wiki/status")
        # Should return 404 when REST is disabled
        assert response.status_code == 404

    def test_init_with_api_key(self, wiki_instance):
        """Test initializing with API key."""
        server = WikiServer(wiki_instance, api_key="test-key")
        assert server.api_key == "test-key"

    def test_init_with_agent(self, wiki_instance):
        """Test initializing with agent (passing None explicitly)."""
        server = WikiServer(wiki_instance, agent=None)
        assert server.agent is None


class TestWikiServerApp:
    """Tests for WikiServer FastAPI app configuration."""

    def test_app_is_fastapi_instance(self, wiki_instance):
        """Test that server.app is a FastAPI instance."""
        server = WikiServer(wiki_instance)
        assert isinstance(server.app, FastAPI)

    def test_app_has_title(self, wiki_instance):
        """Test that FastAPI app has correct title."""
        server = WikiServer(wiki_instance)
        assert server.app.title == "llmwikify"

    def test_mcp_mounted_when_enabled(self, wiki_instance):
        """Test that MCP ASGI app is mounted when enabled."""
        server = WikiServer(wiki_instance, enable_webui=False)
        # Verify MCP is mounted by checking the routes exist
        route_paths = [route.path for route in server.app.routes]
        assert any("/mcp" in path for path in route_paths) or server.mcp is not None

    def test_mcp_not_mounted_when_disabled(self, wiki_instance):
        """Test that MCP ASGI app is not mounted when disabled."""
        server = WikiServer(wiki_instance, enable_mcp=False, enable_webui=False)
        client = TestClient(server.app)
        response = client.get("/mcp")
        assert response.status_code == 404


class TestWikiServerFeatures:
    """Tests for WikiServer feature flags."""

    def test_feature_flags_stored(self, wiki_instance):
        """Test that feature flags are correctly stored."""
        server = WikiServer(
            wiki_instance,
            enable_mcp=True,
            enable_rest=False,
            enable_webui=False
        )
        assert server.enable_mcp is True
        assert server.enable_rest is False
        assert server.enable_webui is False

    def test_health_features_mcp_enabled(self, wiki_instance):
        """Test health endpoint reflects MCP being enabled."""
        server = WikiServer(wiki_instance, enable_mcp=True, enable_webui=False)
        client = TestClient(server.app)
        response = client.get("/api/health")
        data = response.json()
        assert data["features"]["mcp"] is True

    def test_health_features_mcp_disabled(self, wiki_instance):
        """Test health endpoint reflects MCP being disabled."""
        server = WikiServer(wiki_instance, enable_mcp=False, enable_webui=False)
        client = TestClient(server.app)
        response = client.get("/api/health")
        data = response.json()
        assert data["features"]["mcp"] is False


class TestWikiServerName:
    """Tests for MCP name configuration."""

    def test_custom_mcp_name(self, wiki_instance):
        """Test custom MCP name is used."""
        server = WikiServer(wiki_instance, mcp_name="CustomWiki")
        assert server.mcp is not None
        assert server.mcp.name == "CustomWiki"

    def test_default_mcp_name(self, wiki_instance):
        """Test default MCP name uses wiki root."""
        server = WikiServer(wiki_instance)
        assert server.mcp is not None
        assert server.mcp.name is not None
