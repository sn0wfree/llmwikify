"""Integration tests for wiki write page route — token transport.

Token confirmation supports TWO transports (v0.40 final):
  * PRIMARY: ?confirm_token=<id> query string (highest priority when both present)
  * FALLBACK: body {"confirm_token": "<id>"} (back-compat shim)

The mocked DB in this fixture matches any non-empty token against the
fixture's confirmation row, so tests can vary the token string freely
to exercise the priority logic.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
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
    # Accept ANY non-empty token; reject empty / None.
    def _lookup(token):
        if not token:
            return None
        return {
            "id": token,
            "wiki_id": "w1",
            "status": "pending",
            "arguments": {"page_name": "test", "expires_at": time.time() + 300},
        }
    app.state.db.get_confirmation_with_decoded_args = MagicMock(side_effect=_lookup)
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
        """Body is the back-compat shim path; works when no query string is set."""
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

    def test_query_string_token_accepted_fallback(
        self, tmp_path: Path,
    ) -> None:
        """Query string transport (v0.40 PRIMARY) is accepted as the
        canonical mechanism."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            r1 = client.post(
                "/api/wiki/page",
                json={"page_name": "test", "content": "new"},
            )
            assert r1.status_code == 409
            token = r1.json()["detail"]["confirmation_id"]
            # Send token ONLY in query string; body has no confirm_token
            r2 = client.post(
                f"/api/wiki/page?confirm_token={token}",
                json={"page_name": "test", "content": "new"},
            )
            assert r2.status_code == 200, r2.text

    def test_token_from_scoped_route_uses_body(self, tmp_path: Path) -> None:
        """Scoped route honors body fallback path."""
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

    def test_query_string_fallback_scoped_route(self, tmp_path: Path) -> None:
        """Scoped route also accepts ?confirm_token=<id> as primary path."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            r1 = client.post(
                "/api/wiki/w1/page",
                json={"page_name": "test", "content": "new"},
            )
            assert r1.status_code == 409
            token = r1.json()["detail"]["confirmation_id"]
            r2 = client.post(
                f"/api/wiki/w1/page?confirm_token={token}",
                json={"page_name": "test", "content": "new"},
            )
            assert r2.status_code == 200, r2.text

    def test_query_string_wins_over_body_when_both_present(
        self, tmp_path: Path,
    ) -> None:
        """When body and query disagree, query wins (highest priority)."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            # query has valid token "tok_query"; body has a different
            # (still-non-empty-looking) string. Server must use query.
            r = client.post(
                "/api/wiki/page?confirm_token=tok_query",
                json={
                    "page_name": "test",
                    "content": "new",
                    "confirm_token": "tok_body_different",
                },
            )
            assert r.status_code == 200, r.text

    def test_body_wins_when_query_absent(self, tmp_path: Path) -> None:
        """When only body is present, body is used (back-compat path)."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            r = client.post(
                "/api/wiki/page",
                json={
                    "page_name": "test",
                    "content": "new",
                    "confirm_token": "tok_body_only",
                },
            )
            assert r.status_code == 200, r.text

    def test_query_wins_logs_info_on_disagreement(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When both query and body are present and disagree, an INFO
        log records the override WITHOUT leaking either token value."""
        app = _build_app(tmp_path)
        with caplog.at_level(
            logging.INFO,
            logger="llmwikify.interfaces.server.http.wiki.wiki_routes",
        ):
            with TestClient(app) as client:
                r = client.post(
                    "/api/wiki/page?confirm_token=tok_query_leak_test",
                    json={
                        "page_name": "test",
                        "content": "new",
                        "confirm_token": "tok_body_leak_test",
                    },
                )
        assert r.status_code == 200, r.text
        # Exactly one INFO line on the override event
        matching = [
            rec for rec in caplog.records
            if rec.levelno == logging.INFO
            and "overriding body" in rec.getMessage()
        ]
        assert len(matching) == 1
        # The actual token strings must NOT appear in any log message
        full_log = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "tok_query_leak_test" not in full_log
        assert "tok_body_leak_test" not in full_log
