"""Tests for WebUI static file serving and cache headers.

Regression coverage for the SPA chunk-404 bug: stale index.html
in the browser cache referenced now-deleted chunk hashes after
a new build. The fix is two cache headers:

  - ``/assets/*`` (hashed chunks) — ``public, max-age=1y, immutable``
  - ``index.html`` (entry point)  — ``no-cache, must-revalidate``
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llmwikify.interfaces.server.utils.webui import (
    HASHED_ASSET_CACHE_CONTROL,
    INDEX_HTML_CACHE_CONTROL,
    find_webui_dist,
    mount_webui,
)


@pytest.fixture
def client():
    dist = find_webui_dist()
    if dist is None:
        pytest.skip("ui/webui/dist not built; skipping webui cache tests")
    app = FastAPI()
    mount_webui(app)
    return TestClient(app)


class TestCacheHeaders:
    def test_index_html_no_cache(self, client):
        """``GET /`` must revalidate so a new build is picked up."""
        r = client.get("/")
        assert r.status_code == 200
        assert "<script" in r.text
        assert r.headers["Cache-Control"] == INDEX_HTML_CACHE_CONTROL
        assert "no-cache" in r.headers["Cache-Control"]

    def test_spa_route_no_cache(self, client):
        """``GET /edit`` (SPA fallback) is the same index.html — also no-cache."""
        r = client.get("/edit")
        assert r.status_code == 200
        assert r.headers["Cache-Control"] == INDEX_HTML_CACHE_CONTROL

    def test_hashed_asset_long_cache(self, client):
        """Hashed chunks under /assets/* are safe to cache forever."""
        # Find any real chunk filename from the dist directory
        dist = find_webui_dist()
        chunks = list((dist / "assets").glob("index-*.js"))
        if not chunks:
            pytest.skip("No index-*.js chunk in dist to test against")
        r = client.get(f"/assets/{chunks[0].name}")
        assert r.status_code == 200
        assert r.headers["Cache-Control"] == HASHED_ASSET_CACHE_CONTROL
        assert "immutable" in r.headers["Cache-Control"]
        assert "max-age=31536000" in r.headers["Cache-Control"]

    def test_api_routes_unchanged(self, client):
        """Cache policy must not leak onto /api/* routes."""
        r = client.get("/api/does-not-exist")
        assert r.status_code == 404
        assert "Cache-Control" not in r.headers


class TestFindWebuiDist:
    def test_returns_path(self):
        dist = find_webui_dist()
        if dist is not None:
            assert dist.is_dir()
            assert (dist / "index.html").is_file()

    def test_returns_repo_relative_path(self):
        """dist must be at the top-level ui/webui/dist."""
        dist = find_webui_dist()
        if dist is not None:
            assert dist.name == "dist"
            assert dist.parent.name == "webui"
            assert dist.parent.parent.name == "ui"
