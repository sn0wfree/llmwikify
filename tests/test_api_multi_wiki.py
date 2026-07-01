"""Tests for multi-wiki API routes (Phase 2)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwikify import Wiki, WikiRegistry
from llmwikify.interfaces.server.core import WikiServer


@pytest.fixture
def wiki_dirs(tmp_path):
    """Create test wiki directories."""
    wiki_a = tmp_path / "wiki-a"
    wiki_a.mkdir()
    (wiki_a / ".wiki-config.yaml").write_text("")
    Wiki(wiki_a).init()

    wiki_b = tmp_path / "wiki-b"
    wiki_b.mkdir()
    (wiki_b / ".wiki-config.yaml").write_text("")
    Wiki(wiki_b).init()

    return wiki_a, wiki_b


@pytest.fixture
def registry(wiki_dirs):
    """Create a test WikiRegistry with two wikis."""
    wiki_a, wiki_b = wiki_dirs
    config = {
        "wikis": {
            "default": "wiki-a",
            "local": [
                {"id": "wiki-a", "name": "Wiki A", "path": str(wiki_a)},
                {"id": "wiki-b", "name": "Wiki B", "path": str(wiki_b)},
            ],
        }
    }
    reg = WikiRegistry(config)
    reg.initialize()
    yield reg
    reg.close()


@pytest.fixture
def multi_wiki_client(registry):
    """Create a test client with multi-wiki support."""
    server = WikiServer(registry, enable_mcp=False, enable_webui=False)
    return TestClient(server.app)


@pytest.fixture
def single_wiki_client(wiki_dirs):
    """Create a test client with single wiki (backward compatible)."""
    wiki_a, _ = wiki_dirs
    wiki = Wiki(wiki_a)
    server = WikiServer(wiki, enable_mcp=False, enable_webui=False)
    return TestClient(server.app)


class TestMultiWikiAPI:
    """Tests for multi-wiki API endpoints."""

    def test_list_wikis(self, multi_wiki_client):
        """GET /api/wikis returns all wikis."""
        response = multi_wiki_client.get("/api/wikis")
        assert response.status_code == 200
        data = response.json()
        assert "wikis" in data
        assert len(data["wikis"]) == 2
        assert data["default_wiki_id"] == "wiki-a"

    def test_get_wiki_info(self, multi_wiki_client):
        """GET /api/wikis/{wiki_id} returns wiki details."""
        response = multi_wiki_client.get("/api/wikis/wiki-a")
        assert response.status_code == 200
        data = response.json()
        assert data["wiki_id"] == "wiki-a"
        assert data["name"] == "Wiki A"

    def test_get_wiki_info_not_found(self, multi_wiki_client):
        """GET /api/wikis/{wiki_id} returns 404 for unknown wiki."""
        response = multi_wiki_client.get("/api/wikis/nonexistent")
        assert response.status_code == 404

    def test_register_wiki(self, multi_wiki_client, tmp_path):
        """POST /api/wikis registers a new wiki."""
        new_wiki = tmp_path / "new-wiki"
        new_wiki.mkdir()
        (new_wiki / ".wiki-config.yaml").write_text("")

        response = multi_wiki_client.post(
            "/api/wikis",
            json={
                "wiki_id": "new-wiki",
                "name": "New Wiki",
                "type": "local",
                "root": str(new_wiki),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["wiki_id"] == "new-wiki"

    def test_register_wiki_missing_fields(self, multi_wiki_client):
        """POST /api/wikis returns 400 for missing required fields."""
        response = multi_wiki_client.post(
            "/api/wikis",
            json={"name": "Incomplete Wiki"},
        )
        assert response.status_code == 400

    def test_unregister_wiki(self, multi_wiki_client):
        """DELETE /api/wikis/{wiki_id} removes a wiki."""
        response = multi_wiki_client.delete("/api/wikis/wiki-b")
        assert response.status_code == 200

        # Verify it's gone
        response = multi_wiki_client.get("/api/wikis/wiki-b")
        assert response.status_code == 404

    def test_unregister_not_found(self, multi_wiki_client):
        """DELETE /api/wikis/{wiki_id} returns 404 for unknown wiki."""
        response = multi_wiki_client.delete("/api/wikis/nonexistent")
        assert response.status_code == 404

    def test_wiki_status_by_id(self, multi_wiki_client):
        """GET /api/wiki/{wiki_id}/status returns wiki status."""
        response = multi_wiki_client.get("/api/wiki/wiki-a/status")
        assert response.status_code == 200
        data = response.json()
        assert "page_count" in data

    def test_wiki_status_not_found(self, multi_wiki_client):
        """GET /api/wiki/{wiki_id}/status returns 404 for unknown wiki."""
        response = multi_wiki_client.get("/api/wiki/nonexistent/status")
        assert response.status_code == 404

    def test_wiki_search_by_id(self, multi_wiki_client):
        """GET /api/wiki/{wiki_id}/search searches within a wiki."""
        response = multi_wiki_client.get("/api/wiki/wiki-a/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_wiki_lint_by_id(self, multi_wiki_client):
        """GET /api/wiki/{wiki_id}/lint health-checks a wiki."""
        response = multi_wiki_client.get("/api/wiki/wiki-a/lint")
        assert response.status_code == 200

    def test_wiki_recommend_by_id(self, multi_wiki_client):
        """GET /api/wiki/{wiki_id}/recommend gets recommendations."""
        response = multi_wiki_client.get("/api/wiki/wiki-a/recommend")
        assert response.status_code == 200

    def test_cross_wiki_search(self, multi_wiki_client):
        """GET /api/search/cross searches across wikis."""
        response = multi_wiki_client.get("/api/search/cross?q=test")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total_results" in data
        assert "searched_wikis" in data

    def test_cross_wiki_search_specific_wikis(self, multi_wiki_client):
        """GET /api/search/cross with specific wiki IDs."""
        response = multi_wiki_client.get("/api/search/cross?q=test&wikis=wiki-a")
        assert response.status_code == 200
        data = response.json()
        assert "wiki-a" in data["searched_wikis"]

    def test_legacy_status_endpoint(self, multi_wiki_client):
        """GET /api/wiki/status uses default wiki (backward compatible)."""
        response = multi_wiki_client.get("/api/wiki/status")
        assert response.status_code == 200
        data = response.json()
        assert "page_count" in data

    def test_legacy_search_endpoint(self, multi_wiki_client):
        """GET /api/wiki/search uses default wiki (backward compatible)."""
        response = multi_wiki_client.get("/api/wiki/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestSingleWikiAPI:
    """Tests for single-wiki API endpoints (backward compatible)."""

    def test_status(self, single_wiki_client):
        """GET /api/wiki/status returns wiki status."""
        response = single_wiki_client.get("/api/wiki/status")
        assert response.status_code == 200
        data = response.json()
        assert "page_count" in data

    def test_search(self, single_wiki_client):
        """GET /api/wiki/search searches the wiki."""
        response = single_wiki_client.get("/api/wiki/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_lint(self, single_wiki_client):
        """GET /api/wiki/lint health-checks the wiki."""
        response = single_wiki_client.get("/api/wiki/lint")
        assert response.status_code == 200

    def test_recommend(self, single_wiki_client):
        """GET /api/wiki/recommend gets recommendations."""
        response = single_wiki_client.get("/api/wiki/recommend")
        assert response.status_code == 200


class TestHealthEndpoint:
    """Tests for /api/health endpoint."""

    def test_health_single_wiki(self, single_wiki_client):
        """Health check in single-wiki mode."""
        response = single_wiki_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mode"] == "single-wiki"
        assert data["features"]["multi_wiki"] is False

    def test_health_multi_wiki(self, multi_wiki_client):
        """Health check in multi-wiki mode."""
        response = multi_wiki_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mode"] == "multi-wiki"
        assert data["features"]["multi_wiki"] is True
        assert data["wiki_count"] == 2
