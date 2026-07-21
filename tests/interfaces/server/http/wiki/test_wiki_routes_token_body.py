"""Integration tests for wiki write page route — token in body."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_wiki(tmp_path: Path):
    from llmwikify.kernel import Wiki

    wiki = Wiki(tmp_path / "wiki")
    wiki.init()
    # Create a real existing page via the wiki itself so the index knows about it
    wiki.write_page("test", "old content")
    return wiki


def _build_app(tmp_path: Path) -> FastAPI:
    """Build a minimal FastAPI app with just wiki write routes + mock db."""
    from llmwikify.interfaces.server.http.wiki import wiki_routes

    app = FastAPI()
    wiki = _make_wiki(tmp_path)

    from llmwikify.kernel.multi_wiki.instance import WikiType
    from llmwikify.kernel.multi_wiki.registry import WikiRegistry

    registry = WikiRegistry(config={})
    registry.register_wiki(
        wiki_id="w1",
        name="w1",
        root=wiki.root,
        wiki_type=WikiType.LOCAL,
        is_default=True,
    )
    app.state.db = MagicMock()
    app.state.db.get_confirmation_with_decoded_args = MagicMock(
        return_value={
            "id": "tok1",
            "wiki_id": "w1",
            "status": "pending",
            "arguments": {"page_name": "test", "expires_at": time.time() + 300},
        },
    )
    app.state.db.save_confirmation = MagicMock()
    app.state.db.delete_confirmation = MagicMock()

    # Inject a fake _get_wiki_db_and_id
    import llmwikify.interfaces.server.http.wiki.wiki_routes as wr

    wr._get_wiki_db_and_id = lambda registry, wiki_id=None: (
        app.state.db, wiki_id or "w1",
    )
    wiki_routes.register_wiki_routes(app, registry)
    return app


class TestWikiWritePageTokenInBody:
    def test_token_from_body_works(self, tmp_path: Path) -> None:
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            r1 = client.post(
                "/api/wiki/page",
                json={"page_name": "test", "content": "new"},
            )
            assert r1.status_code == 409
            token = r1.json()["detail"]["confirmation_id"]
            r2 = client.post(
                "/api/wiki/page",
                json={"page_name": "test", "content": "new", "confirm_token": token},
            )
            assert r2.status_code == 200, r2.text

    def test_query_string_token_no_longer_supported(
        self, tmp_path: Path,
    ) -> None:
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            # Token in query string is ignored; body lacks token → 409
            r = client.post(
                "/api/wiki/page?confirm_token=whatever",
                json={"page_name": "test", "content": "new"},
            )
            assert r.status_code == 409

    def test_token_from_scoped_route_uses_body(self, tmp_path: Path) -> None:
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            r1 = client.post(
                "/api/wiki/w1/page",
                json={"page_name": "test", "content": "new"},
            )
            assert r1.status_code == 409
            token = r1.json()["detail"]["confirmation_id"]
            r2 = client.post(
                "/api/wiki/w1/page",
                json={"page_name": "test", "content": "new", "confirm_token": token},
            )
            assert r2.status_code == 200, r2.text
