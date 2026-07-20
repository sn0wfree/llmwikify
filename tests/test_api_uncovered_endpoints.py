"""Tests for endpoints in routes.py that had zero test coverage.

Covers Phase C prep (Q3): the 6 endpoints identified by the deep dive:

- GET /api/wiki/suggest_synthesis         (routes.py:190)
- PUT /api/wikis/{wiki_id}                (routes.py:279)  update_wiki
- POST /api/wikis/{wiki_id}/reload        (routes.py:303)  reload_wiki
- GET /api/wikis/{wiki_id}/health         (routes.py:311)  wiki_health
- POST /api/wikis/scan                    (routes.py:320)  scan_wikis
- POST /api/log/error                     (routes.py:522)  log_client_error
"""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwikify import Wiki, WikiRegistry
from llmwikify.interfaces.server.core import WikiServer


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    """Create a single initialized wiki directory."""
    root = tmp_path / "wiki-a"
    root.mkdir()
    (root / ".wiki-config.yaml").write_text("")
    Wiki(root).init()
    return root


@pytest.fixture
def registry(wiki_root: Path) -> WikiRegistry:
    """Build a single-wiki WikiRegistry (simpler than multi-wiki fixture)."""
    config = {
        "wikis": {
            "default": "wiki-a",
            "local": [
                {"id": "wiki-a", "name": "Wiki A", "path": str(wiki_root)},
            ],
        }
    }
    reg = WikiRegistry(config)
    reg.initialize()
    yield reg
    reg.close()


@pytest.fixture
def client(registry: WikiRegistry) -> TestClient:
    """TestClient with local_mode (no JWT).

    ``raise_server_exceptions=False`` lets us assert on 500 responses that
    would otherwise re-raise (e.g. the reload_wiki KeyError path).
    """
    server = WikiServer(
        registry, enable_mcp=False, enable_webui=False, local_mode=True
    )
    return TestClient(server.app, raise_server_exceptions=False)


class TestSuggestSynthesis:
    """GET /api/wiki/suggest_synthesis — cross-source synthesis suggestions."""

    def test_returns_suggestions_shape(self, client: TestClient) -> None:
        """Empty wiki returns the synthesis payload with zero counts."""
        response = client.get("/api/wiki/suggest_synthesis")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "suggestions" in data
        assert "sources_analyzed" in data
        assert "summary" in data
        assert data["sources_analyzed"] == 0
        assert data["suggestions"] == []

    def test_with_source_name_param(self, client: TestClient) -> None:
        """Query string source_name is forwarded (no crash on missing source)."""
        response = client.get("/api/wiki/suggest_synthesis?source_name=missing.md")
        assert response.status_code == 200
        data = response.json()
        assert "suggestions" in data


class TestUpdateWiki:
    """PUT /api/wikis/{wiki_id} — update name / set default."""

    def test_update_name(self, client: TestClient) -> None:
        """PUT /api/wikis/{id} updates the instance name."""
        response = client.put(
            "/api/wikis/wiki-a",
            json={"name": "Renamed Wiki"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["wiki_id"] == "wiki-a"
        assert data["name"] == "Renamed Wiki"

    def test_update_is_default(
        self, client: TestClient, registry: WikiRegistry
    ) -> None:
        """PUT /api/wikis/{id} with is_default=true flips the default."""
        response = client.put(
            "/api/wikis/wiki-a",
            json={"is_default": True},
        )
        assert response.status_code == 200
        assert registry.get_default_wiki_id() == "wiki-a"

    def test_update_not_found(self, client: TestClient) -> None:
        """PUT /api/wikis/{id} returns 404 for unknown wiki."""
        response = client.put(
            "/api/wikis/nonexistent",
            json={"name": "Ghost"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestReloadWiki:
    """POST /api/wikis/{wiki_id}/reload — rebuild FTS5 index."""

    def test_reload_success(self, client: TestClient) -> None:
        """Reloading an existing wiki returns status=success."""
        response = client.post("/api/wikis/wiki-a/reload")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "wiki-a" in data["message"].lower()

    def test_reload_not_found(self, client: TestClient) -> None:
        """Reloading an unknown wiki returns 404 (KeyError caught)."""
        response = client.post("/api/wikis/nonexistent/reload")
        assert response.status_code == 404


class TestWikiHealth:
    """GET /api/wikis/{wiki_id}/health — wiki health check."""

    def test_health_ok(self, client: TestClient) -> None:
        """Health endpoint returns status payload for a known wiki."""
        response = client.get("/api/wikis/wiki-a/health")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_health_unknown_wiki(self, client: TestClient) -> None:
        """Health endpoint returns 404 when wiki_id is unknown."""
        response = client.get("/api/wikis/nonexistent/health")
        assert response.status_code == 404
        assert "detail" in response.json()


class TestScanWikis:
    """POST /api/wikis/scan — scan directories for new wikis.

    Validates the path-traversal guard (only $HOME allowed).
    """

    def test_scan_accepts_home_relative(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scan paths under $HOME are accepted."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        scan_root = tmp_path / "scan-target"
        scan_root.mkdir()
        (scan_root / ".wiki-config.yaml").write_text("")

        response = client.post(
            "/api/wikis/scan",
            json={"scan_paths": [str(scan_root)], "scan_depth": 1},
        )
        assert response.status_code == 200
        data = response.json()
        assert "new_wikis" in data
        assert "count" in data

    def test_scan_rejects_outside_home(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scan paths outside $HOME are rejected with 400 (path-traversal guard)."""
        # Set HOME to tmp_path so we can craft an "outside" path
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        outside = tmp_path / "outside-wikis"
        outside.mkdir()

        response = client.post(
            "/api/wikis/scan",
            json={"scan_paths": [str(outside)], "scan_depth": 1},
        )
        assert response.status_code == 400
        assert "outside home" in response.json()["detail"].lower()


class TestLogClientError:
    """POST /api/log/error — frontend error log receiver."""

    def test_api_error_log(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """api-error type is routed to client.errors logger."""
        with caplog.at_level(logging.ERROR, logger="client.errors"):
            response = client.post(
                "/api/log/error",
                json={
                    "type": "api-error",
                    "method": "GET",
                    "url": "/api/wiki/status",
                    "status": 500,
                    "contentType": "application/json",
                    "requestBody": '{"q":"test"}',
                    "bodySnippet": '{"error":"boom"}',
                },
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # At least one log record was emitted under client.errors
        assert any(
            "api-error" in record.message for record in caplog.records
        )

    def test_fetch_error_log(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """fetch-error type is routed to client.errors logger."""
        with caplog.at_level(logging.ERROR, logger="client.errors"):
            response = client.post(
                "/api/log/error",
                json={
                    "type": "fetch-error",
                    "method": "POST",
                    "endpoint": "/api/agent/chat",
                    "message": "NetworkError when attempting to fetch resource.",
                },
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert any(
            "fetch-error" in record.message for record in caplog.records
        )

    def test_unknown_error_log(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """unknown / js error type includes stack trace."""
        with caplog.at_level(logging.ERROR, logger="client.errors"):
            response = client.post(
                "/api/log/error",
                json={
                    "type": "ReferenceError",
                    "message": "x is not defined",
                    "url": "https://example.com/app.js",
                    "filename": "app.js",
                    "lineno": 42,
                    "colno": 7,
                    "stack": "ReferenceError: x is not defined\n    at handler (app.js:42:7)",
                },
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert any(
            "ReferenceError" in record.message for record in caplog.records
        )

    def test_invalid_json_body(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-JSON body is swallowed silently and endpoint still returns 200."""
        with caplog.at_level(logging.ERROR, logger="client.errors"):
            response = client.post(
                "/api/log/error",
                content=b"this is not json",
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
