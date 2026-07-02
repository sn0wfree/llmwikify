"""Tests for interfaces.server.http.auth_routes + JWTAuthMiddleware.

Phase 2.5: PAT-based auth (no passwords).
Phase 2a integration tests using FastAPI TestClient (sync).
Covers:
  - POST /auth/register (email → PAT + JWT)
  - POST /auth/verify (PAT → JWT)
  - POST /auth/tokens (create PAT, authenticated)
  - GET /auth/tokens (list PATs)
  - DELETE /auth/tokens/{id} (revoke PAT)
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
    ApiKeyRepository,
    TokenClaims,
    UserRepository,
    encode,
    generate_pat,
    hash_pat,
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
    """Each test gets its own LLMWIKIFY_HOME so the auth.db is fresh."""
    monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
    yield


class _FakeRegistry:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids

    def list_wikis(self):
        from types import SimpleNamespace
        return [SimpleNamespace(wiki_id=i) for i in self.ids]


# ─── /auth/register + /auth/verify happy path ────────────────────


class TestRegisterVerifyFlow:
    def test_register_creates_user_and_returns_pat(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/register",
            json={"email": "alice@example.com"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "pat" in body
        assert body["pat"].startswith("llmw_")
        assert "access_token" in body
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["is_first_admin"] is True
        assert body["user"]["can_edit"] is True

    def test_register_closed_after_first_user(self):
        """Registration is closed once a user exists (403, not 409)."""
        UserRepository().create(email="first@example.com")
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/register",
            json={"email": "second@example.com"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "registration_closed"

    def test_register_invalid_email_returns_400(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/register",
            json={"email": "not-an-email"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_email"

    def test_verify_pat_returns_token(self):
        # Register first to get a PAT.
        client = TestClient(_make_app())
        reg_resp = client.post(
            "/api/auth/register",
            json={"email": "bob@example.com"},
        )
        pat = reg_resp.json()["pat"]

        # Verify the PAT.
        resp = client.post(
            "/api/auth/verify",
            json={"pat": pat},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["user"]["email"] == "bob@example.com"
        # Cookie is set.
        assert "llmwikify_token" in resp.cookies

    def test_verify_wrong_pat_returns_401(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/verify",
            json={"pat": "llmw_000000000000000000000000000000000000000000000000"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_pat"

    def test_verify_missing_pat_returns_400(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/verify",
            json={"pat": ""},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "missing_pat"

    def test_me_after_register(self):
        client = TestClient(_make_app())
        client.post(
            "/api/auth/register",
            json={"email": "c@e.com"},
        )
        # Verify the PAT to set the cookie.
        # First get the PAT from the DB.
        repo = UserRepository()
        user = repo.get_by_email("c@e.com")
        ak_repo = ApiKeyRepository()
        # Use verify to set cookie.
        client.post(
            "/api/auth/verify",
            json={"pat": "invalid"},  # This won't set cookie
        )
        # We need to generate a valid PAT. Register gives us one.
        # Re-register to get a PAT (will fail since email exists).
        # Instead, create a PAT directly and verify.
        plain, pat_hash = generate_pat()
        ak_repo.create(
            user_id=user.id,
            key_prefix=plain[:12],
            key_hash=pat_hash,
            name="test",
        )
        resp = client.post(
            "/api/auth/verify",
            json={"pat": plain},
        )
        assert resp.status_code == 200
        # Now /auth/me should work.
        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        body = me_resp.json()
        assert body["authenticated"] is True
        assert body["user"]["can_edit"] is True

    def test_me_without_cookie(self):
        client = TestClient(_make_app(public_read=False))
        resp = client.get("/api/auth/me")
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
            resp = client.get("/api/auth/me")
            assert resp.status_code == 200
            assert resp.json()["user"]["local_mode"] is True
            assert resp.json()["user"]["can_edit"] is True


# ─── /auth/tokens (PAT management, authenticated) ────────────────


class TestTokenManagement:
    def _auth_client(self, email: str = "tokens@example.com") -> TestClient:
        """Register a user and return a client with a valid JWT cookie."""
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/register",
            json={"email": email},
        )
        assert resp.status_code == 200
        pat = resp.json()["pat"]
        # Verify to get the cookie.
        verify_resp = client.post(
            "/api/auth/verify",
            json={"pat": pat},
        )
        assert verify_resp.status_code == 200
        return client

    def test_create_token(self):
        client = self._auth_client()
        resp = client.post(
            "/api/auth/tokens",
            json={"name": "laptop"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pat"].startswith("llmw_")
        assert body["key"]["name"] == "laptop"

    def test_list_tokens(self):
        client = self._auth_client()
        # Create two more tokens (register already created one).
        client.post("/api/auth/tokens", json={"name": "k1"})
        client.post("/api/auth/tokens", json={"name": "k2"})
        resp = client.get("/api/auth/tokens")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 3  # 1 from register + 2 created

    def test_revoke_token(self):
        client = self._auth_client()
        # Create a token.
        create_resp = client.post("/api/auth/tokens", json={"name": "revoke-me"})
        key_id = create_resp.json()["key"]["id"]
        # Revoke it.
        resp = client.delete(f"/api/auth/tokens/{key_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # List should show revoked.
        list_resp = client.get("/api/auth/tokens")
        keys = list_resp.json()["keys"]
        revoked = [k for k in keys if k["id"] == key_id]
        assert len(revoked) == 1
        assert revoked[0]["revoked_at"] is not None

    def test_revoke_nonexistent_token_returns_404(self):
        client = self._auth_client()
        resp = client.delete("/api/auth/tokens/nonexistent-id")
        assert resp.status_code == 404

    def test_unauthenticated_tokens_returns_401(self):
        client = TestClient(_make_app())
        resp = client.get("/api/auth/tokens")
        assert resp.status_code == 401

    def test_unauthenticated_create_token_returns_401(self):
        client = TestClient(_make_app())
        resp = client.post("/api/auth/tokens", json={"name": "test"})
        assert resp.status_code in (401, 403)  # 401 if no public_read, 403 if public_read


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

        # Ensure JWT secret exists in the fake keyring.
        secret = set_secret()
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
        assert resp.json()["error"] in ("token_expired", "invalid_token")

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

    def test_local_mode_register_creates_admin(self):
        """In local mode, /auth/register should create the first admin
        even without prior auth."""
        with patch(
            "llmwikify.interfaces.server.http.auth_routes.is_local_default",
            return_value=True,
        ):
            client = TestClient(_make_app(local_mode=True, public_read=True))
            resp = client.post(
                "/api/auth/register",
                json={"email": "localadmin@e.com"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["user"]["local_mode"] is True
            assert body["user"]["is_first_admin"] is True


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
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "share_token_not_here"
