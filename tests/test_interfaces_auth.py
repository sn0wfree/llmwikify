"""Tests for interfaces.server.http.auth_routes + JWTAuthMiddleware.

Phase 2a integration tests using FastAPI TestClient (sync).
Covers:
  - POST /auth/login (cookie set, /me reflects)
  - GET /auth/me (decision 1: friendly shape, not raw scope)
  - JWTAuthMiddleware scope + wikis claim enforcement (decisions 4, 7)
  - Local mode pass-through (decision 12)
  - Public read + write require JWT (decisions 1, 4)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Force a per-test temp home BEFORE importing auth so the JWT secret
# is generated into a sandboxed keyring.
TEST_HOME = Path(tempfile.mkdtemp(prefix="llmwikify_interfaces_auth_"))
os.environ["LLMWIKIFY_HOME"] = str(TEST_HOME)


# Mock keyring with an in-process dict backend so tests are hermetic.
_KEYRING_STORE: dict[tuple[str, str], str] = {}


def _fake_keyring_set_password(service: str, user: str, value: str) -> None:
    _KEYRING_STORE[(service, user)] = value


def _fake_keyring_get_password(service: str, user: str) -> str | None:
    return _KEYRING_STORE.get((service, user))


def _fake_keyring_delete_password(service: str, user: str) -> None:
    _KEYRING_STORE.pop((service, user), None)


# Apply keyring patches at module import. We replace keyring's
# get/set/delete functions with our in-memory dict backend. This is a
# safe global mutation because tests are isolated by LLMWIKIFY_HOME
# (per-test tmp_path fixture).
import keyring  # noqa: E402
import keyring.errors  # noqa: E402

keyring.set_password = _fake_keyring_set_password  # type: ignore[assignment]
keyring.get_password = _fake_keyring_get_password  # type: ignore[assignment]
keyring.delete_password = _fake_keyring_delete_password  # type: ignore[assignment]


from llmwikify.foundation.auth import (  # noqa: E402
    TokenClaims,
    UserRepository,
    encode,
    require_secret,
    set_secret,
)
from llmwikify.interfaces.server.http.auth_routes import auth_router  # noqa: E402
from llmwikify.interfaces.server.http.middleware import JWTAuthMiddleware  # noqa: E402


def _make_app(*, local_mode: bool = False, public_read: bool = True) -> FastAPI:
    """Build a minimal FastAPI app with auth_routes + JWTAuthMiddleware.

    We include a fake /api/wiki/{wiki_id} route so we can test the
    wikis claim enforcement (decision 7).
    """
    app = FastAPI()
    # Set up JWT secret in our fake keyring.
    _KEYRING_STORE.clear()
    set_secret(b"x" * 32)
    app.include_router(auth_router)
    secret = require_secret()
    app.add_middleware(
        JWTAuthMiddleware,
        secret=secret,
        public_read=public_read,
        local_mode=local_mode,
    )

    # Fake wiki route for testing scope/wikis claim.
    @app.get("/api/wiki/{wiki_id}/info")
    async def wiki_info(wiki_id: str):
        return {"wiki_id": wiki_id}

    @app.post("/api/wiki/{wiki_id}/pages")
    async def wiki_create(wiki_id: str):
        return {"created": wiki_id}

    @app.get("/api/wiki/all")
    async def wiki_all():
        return {"all": True}

    # Set a fake wiki registry on app.state.
    app.state.wiki_registry = _FakeRegistry(["main", "side"])
    return app


@pytest.fixture(autouse=True)
def _fresh_auth_db(monkeypatch, tmp_path):
    """Each test gets its own LLMWIKIFY_HOME so the auth.db is fresh.

    Without this, test order matters (later tests see users created by
    earlier tests, and the local-mode branch in /auth/login is skipped
    because repo.exists() is True).
    """
    monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
    yield


class _FakeRegistry:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids

    def list_wikis(self):
        from types import SimpleNamespace
        return [SimpleNamespace(wiki_id=i) for i in self.ids]


# ─── /auth/login + /auth/me happy path ──────────────────────────


class TestLoginMeFlow:
    def test_login_sets_cookie_and_returns_token(self):
        UserRepository().create(
            email="alice@example.com",
            password="password123",
            is_first_admin=True,
        )
        client = TestClient(_make_app())
        resp = client.post(
            "/auth/login",
            data={"username": "alice@example.com", "password": "password123"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "access_token" in body
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["is_first_admin"] is True
        assert body["user"]["can_edit"] is True
        # Cookie is set.
        assert "llmwikify_token" in resp.cookies

    def test_login_wrong_password(self):
        UserRepository().create(
            email="bob@example.com",
            password="password123",
        )
        client = TestClient(_make_app())
        resp = client.post(
            "/auth/login",
            data={"username": "bob@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_credentials"

    def test_login_unknown_email_also_returns_401(self):
        # Don't leak which is wrong — same error.
        client = TestClient(_make_app())
        resp = client.post(
            "/auth/login",
            data={"username": "nobody@example.com", "password": "whatever"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_credentials"

    def test_me_with_cookie(self):
        UserRepository().create(email="c@e.com", password="password123", is_first_admin=True)
        client = TestClient(_make_app())
        client.post(
            "/auth/login",
            data={"username": "c@e.com", "password": "password123"},
        )
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        # Decision 1: friendly shape, not raw scope.
        assert body["user"]["can_edit"] is True
        assert "scope" not in body["user"]
        assert "sub" not in body["user"]

    def test_me_without_cookie(self):
        client = TestClient(_make_app(public_read=False))
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_local_mode_marker(self):
        # TestClient's default request.url.hostname is "testserver",
        # which is NOT loopback. We patch is_local_default for the
        # duration of this test so the route treats us as local.
        with patch(
            "llmwikify.interfaces.server.http.auth_routes.is_local_default",
            return_value=True,
        ):
            client = TestClient(_make_app(local_mode=True, public_read=True))
            resp = client.get("/auth/me")
            assert resp.status_code == 200
            assert resp.json()["user"]["local_mode"] is True
            assert resp.json()["user"]["can_edit"] is True


# ─── JWTAuthMiddleware: scope + wikis claim (decisions 1, 4, 7) ────


class TestMiddlewareScope:
    def _make_token(self, scope: str, wikis: list[str]) -> str:
        secret = require_secret()
        c = TokenClaims.new(sub="user:fake", scope=scope, wikis=wikis, ttl_seconds=60)
        return encode(c, secret)

    def test_public_read_allows_get_without_token(self):
        client = TestClient(_make_app(public_read=True, local_mode=False))
        resp = client.get("/api/wiki/main/info")
        assert resp.status_code == 200

    def test_no_public_read_requires_token(self):
        client = TestClient(_make_app(public_read=False, local_mode=False))
        resp = client.get("/api/wiki/main/info")
        assert resp.status_code == 401

    def test_post_requires_write_scope(self):
        client = TestClient(_make_app(public_read=True, local_mode=False))
        # Read-scope JWT cannot POST.
        token = self._make_token(scope="read", wikis=["main"])
        resp = client.post(
            "/api/wiki/main/pages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "forbidden_scope"

    def test_write_scope_can_post(self):
        client = TestClient(_make_app(public_read=True, local_mode=False))
        token = self._make_token(scope="write", wikis=["main"])
        resp = client.post(
            "/api/wiki/main/pages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["created"] == "main"

    def test_wikis_claim_enforced(self):
        client = TestClient(_make_app(public_read=True, local_mode=False))
        # Token only covers "main", not "side".
        token = self._make_token(scope="write", wikis=["main"])
        resp = client.get(
            "/api/wiki/side/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "forbidden_wiki"

    def test_wildcard_wikis_allow_any(self):
        client = TestClient(_make_app(public_read=True, local_mode=False))
        token = self._make_token(scope="write", wikis=["*"])
        resp = client.get(
            "/api/wiki/side/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_expired_token_401(self):
        import time

        secret = require_secret()
        c = TokenClaims(
            sub="user:fake",
            scope="read",
            wikis=["*"],
            exp=int(time.time()) - 1,
            iat=0,
        )
        token = encode(c, secret)
        client = TestClient(_make_app(public_read=False, local_mode=False))
        resp = client.get(
            "/api/wiki/main/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "token_expired"

    def test_invalid_signature_401(self):
        client = TestClient(_make_app(public_read=False, local_mode=False))
        resp = client.get(
            "/api/wiki/main/info",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_token"


# ─── Local mode (decision 12) ──────────────────────────────────


class TestLocalModePassThrough:
    def test_local_mode_allows_post_without_token(self):
        client = TestClient(_make_app(local_mode=True, public_read=True))
        # No token, no public_read check — local trust.
        resp = client.post("/api/wiki/main/pages")
        assert resp.status_code == 200

    def test_local_mode_allows_get_without_token(self):
        client = TestClient(_make_app(local_mode=True, public_read=True))
        resp = client.get("/api/wiki/main/info")
        assert resp.status_code == 200
        assert resp.json()["wiki_id"] == "main"

    def test_local_mode_login_returns_marker(self):
        # TestClient's default request.url.hostname is "testserver",
        # which is NOT loopback. Patch is_local_default for this test.
        with patch(
            "llmwikify.interfaces.server.http.auth_routes.is_local_default",
            return_value=True,
        ):
            client = TestClient(_make_app(local_mode=True, public_read=True))
            resp = client.post(
                "/auth/login",
                data={"username": "any@e.com", "password": "any"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["access_token"] == "local-mode-no-auth"
            assert body["user"]["local_mode"] is True


# ─── /auth/me with share token (Phase 3 prep) ──────────────────


class TestShareTokenRejection:
    def test_me_with_share_token_returns_401(self):
        secret = require_secret()
        c = TokenClaims.new(
            sub="share:abc",
            scope="read",
            wikis=["main"],
            ttl_seconds=60,
        )
        token = encode(c, secret)
        client = TestClient(_make_app(public_read=True, local_mode=False))
        client.cookies.clear()
        client.cookies["llmwikify_token"] = token
        resp = client.get("/auth/me")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "share_token_not_here"
