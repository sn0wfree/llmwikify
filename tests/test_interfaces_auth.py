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

    def test_me_invalid_bearer_returns_401_p1_7(self):
        """P1-7: a present-but-invalid Bearer must 401 so the SPA can clear."""
        with patch(
            "llmwikify.interfaces.server.http.auth_routes.is_local_default",
            return_value=True,
        ):
            client = TestClient(_make_app(local_mode=True, public_read=True))
            resp = client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer not-a-real-jwt"},
            )
            assert resp.status_code == 401
            assert resp.json()["detail"]["error"] == "invalid_token"

    def test_me_valid_bearer_returns_200(self):
        """Bearer JWT (no cookie) is accepted on /me."""
        # Register to create a real user + get identity.
        client = TestClient(_make_app())
        reg = client.post("/api/auth/register", json={"email": "bearer@e.com"})
        assert reg.status_code == 200
        pat = reg.json()["pat"]
        ver = client.post("/api/auth/verify", json={"pat": pat})
        assert ver.status_code == 200
        access = ver.json()["access_token"]
        client2 = TestClient(_make_app())
        resp = client2.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user"]["email"] == "bearer@e.com"


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
        assert resp.status_code in (
            401,
            403,
        )  # 401 if no public_read, 403 if public_read


# ─── JWTAuthMiddleware: scope + wikis claim (decisions 1, 4, 7) ────


class TestMiddlewareScope:
    @staticmethod
    def _ensure_user(email: str = "mw@e.com"):
        """Real user row — P4b rejects tokens for missing users (401)."""
        from llmwikify.foundation.auth import UserRepository

        repo = UserRepository()
        u = repo.get_by_email(email)
        if u is None:
            u = repo.create(email=email, is_first_admin=False)
        return u

    def _make_token(self, scope: str, wikis: list[str]) -> str:
        secret = require_secret()
        user = self._ensure_user()
        c = TokenClaims.new(
            sub=f"user:{user.id}", scope=scope, wikis=wikis, ttl_seconds=60
        )
        return encode(c, secret)

    def test_no_token_returns_401_p4b(self):
        """P4b: 无 token 不允许看 — public_read no longer opens GETs."""
        client = TestClient(_make_app(public_read=True, local_mode=False))
        resp = client.get("/api/wiki/main/info")
        assert resp.status_code == 401
        assert resp.json()["error"] == "auth_required"

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
        # P4a: the middleware now rejects non-user subjects first
        # (invalid_subject); the route-level share_token_not_here remains
        # as defense-in-depth if the request ever bypasses middleware.
        body = resp.json()
        err = body.get("detail", body).get("error") if isinstance(body.get("detail", body), dict) else body.get("error")
        assert err in ("invalid_subject", "share_token_not_here")


# ─── P5: grants API + permission matrix ─────────────────────────


class TestGrantsAPIP5:
    """P5: /me permissions + grants CRUD (admin-only)."""

    @staticmethod
    def _admin_client(email: str = "root@e.com") -> TestClient:
        """Register first admin + verify PAT → cookie session."""
        client = TestClient(_make_app())
        resp = client.post("/api/auth/register", json={"email": email})
        assert resp.status_code == 200
        pat = resp.json()["pat"]
        ver = client.post("/api/auth/verify", json={"pat": pat})
        assert ver.status_code == 200
        return client

    def test_me_returns_permission_matrix(self):
        client = self._admin_client()
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["authenticated"] is True
        perms = body.get("permissions")
        assert perms is not None
        # Admin → live accessible = all known wikis from the fake registry.
        assert set(perms["accessible_wikis"]) == {"main", "side"}
        assert perms["scope"] == "write"

    def test_grants_crud(self):
        client = self._admin_client()
        # List (empty initially, or whatever exists).
        r = client.get("/api/auth/grants")
        assert r.status_code == 200
        assert "grants" in r.json()

        # Create a user to grant to.
        from llmwikify.foundation.auth import UserRepository

        u = UserRepository().create(email="bob@e.com", is_first_admin=False)

        # Grant.
        r2 = client.post(
            "/api/auth/grants",
            json={
                "principal_type": "user",
                "principal_id": u.id,
                "wiki_id": "main",
                "read": True,
                "write": True,
            },
        )
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

        # List contains it.
        r3 = client.get("/api/auth/grants")
        grants = r3.json()["grants"]
        assert any(
            g["principal_id"] == u.id and g["wiki_id"] == "main" for g in grants
        )

        # Revoke.
        r4 = client.request(
            "DELETE",
            "/api/auth/grants",
            json={
                "principal_type": "user",
                "principal_id": u.id,
                "wiki_id": "main",
            },
        )
        assert r4.status_code == 200
        assert r4.json()["removed"] is True

        r5 = client.get("/api/auth/grants")
        assert not any(
            g["principal_id"] == u.id and g["wiki_id"] == "main"
            for g in r5.json()["grants"]
        )

    def test_grants_require_admin(self):
        """Non-admin → 403 admin_required (Q4)."""
        from llmwikify.foundation.auth import UserRepository

        # First make an admin (needed for registration_closed), then a user.
        self._admin_client("root@e.com")
        UserRepository().create(email="eve@e.com", is_first_admin=False)

        # Build a session for the non-admin via a fresh app + verify.
        client = TestClient(_make_app())
        # Create a PAT for eve directly.
        u = UserRepository().get_by_email("eve@e.com")
        assert u is not None
        from llmwikify.foundation.auth import ApiKeyRepository, generate_pat

        plain, ph = generate_pat()
        ApiKeyRepository().create(
            user_id=u.id, key_prefix=plain[:12], key_hash=ph, name="eve"
        )
        ver = client.post("/api/auth/verify", json={"pat": plain})
        assert ver.status_code == 200

        r = client.get("/api/auth/grants")
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "admin_required"

        r2 = client.post(
            "/api/auth/grants",
            json={
                "principal_type": "user",
                "principal_id": u.id,
                "wiki_id": "main",
                "read": True,
            },
        )
        assert r2.status_code == 403

    def test_users_and_groups_endpoints(self):
        client = self._admin_client()
        r = client.get("/api/auth/users")
        assert r.status_code == 200
        assert any(u["email"] == "root@e.com" for u in r.json()["users"])

        r2 = client.get("/api/auth/groups")
        assert r2.status_code == 200
        assert "groups" in r2.json()

    def test_grants_validation(self):
        client = self._admin_client()
        r = client.post(
            "/api/auth/grants",
            json={"principal_type": "user", "principal_id": "", "wiki_id": "x"},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_grant"
