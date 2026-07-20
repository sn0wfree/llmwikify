"""Unit tests for v0.32 Phase 9: routes migration.

Covers:

  - 1 router is at the new home (interfaces/server/http/chat_sse)
  - The chat_sse router is importable
  - Backward-compat shims (4 paths) re-export correctly
  - The L4 routes.py uses the new home (no apps.agent.routes refs)
  - The L3→L4 dependency in apps/chat/routes.py was removed
  - Architecture contracts stay green

Target: 30+ tests, no I/O, no real FastAPI server.

v0.36 update: the legacy ``research`` router was consolidated into
the unified agent SPA (see ``chat_sse.py``); the orphaned
``interfaces/server/http/research.py`` was removed along with the
rest of the dead legacy ``apps/research/`` engine. The tests that
asserted the research router's existence were updated to assert
that the consolidated chat_sse router is the single source of
truth instead.
"""

from __future__ import annotations

import pytest

# ─── New home: routers importable ─────────────────────────────


class TestNewHomeImports:
    """The migrated chat_sse router is importable from
    ``llmwikify.interfaces.server.http``.

    v0.36 update: the legacy ``research`` router was consolidated
    into the unified agent SPA and its module was removed.
    """

    def test_chat_sse_imports(self) -> None:
        from llmwikify.interfaces.server.http.agent._common import (
            get_agent_service,
            router,
            set_agent_service,
        )
        assert router is not None
        assert callable(set_agent_service)
        assert callable(get_agent_service)

    def test_research_router_removed(self) -> None:
        """The orphaned /api/research router was removed in v0.36;
        research functionality lives in the unified agent SPA."""
        import importlib
        with pytest.raises(ImportError):
            importlib.import_module("llmwikify.interfaces.server.http.research")

    def test_no_apps_agent_routes_remain(self) -> None:
        """apps/agent/routes/ should be GONE after the migration."""
        import importlib
        with pytest.raises(ImportError):
            importlib.import_module("llmwikify.apps.agent.routes")
        with pytest.raises(ImportError):
            importlib.import_module("llmwikify.apps.agent.routes.agent")
        with pytest.raises(ImportError):
            importlib.import_module("llmwikify.apps.agent.routes.ppt")
        with pytest.raises(ImportError):
            importlib.import_module("llmwikify.apps.agent.routes.research")


# ─── Router attributes (APIRouter + prefix) ─────────────────────


class TestRouterAttributes:
    """The chat_sse router has the expected APIRouter prefix and tags."""

    def test_chat_sse_router_prefix(self) -> None:
        from llmwikify.interfaces.server.http.agent._common import router
        assert router.prefix == "/api/agent"
        assert "agent" in router.tags

    def test_routers_have_routes(self) -> None:
        """The chat_sse router should have at least 1 registered route."""
        from llmwikify.interfaces.server.http.agent._common import router as c
        assert len(c.routes) > 0


# ─── L4 routes.py integrity ──────────────────────────────────────


class TestL4RoutesPy:
    """Verify the routes module at L4."""

    def test_routes_py_does_not_import_apps_agent_routes(self) -> None:
        """routes.py should NOT import from apps.agent.routes."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "apps.agent.routes" not in src

    def test_routes_py_imports_chat_sse_from_new_home(self) -> None:
        """routes.py should import chat_sse from the new location."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces.server.http.agent._common import" in src

    def test_routes_py_imports_research_from_new_home(self) -> None:
        """routes.py should import research from the new location.

        Phase 1 (v0.36): research router was consolidated into
        the unified agent SPA. The explicit research import is
        no longer needed in routes.py.
        """
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        # Research routes are now handled by the SPA; no explicit
        # import is required. Verify agent_router is imported.
        assert "from llmwikify.interfaces.server.http.agent._common import" in src


# ─── L3 chat routes ─────────────────────────────────────────────


class TestL3ChatRoutes:
    """apps/chat/routes.py should not import from interfaces/.

    Note (v0.42): the legacy apps/chat/routes.py was git-mv'd to
    archive/llmwikify_v0_41_legacy/chat_legacy/routes.py along with
    the rest of the v0.41 autoresearch layer. The corresponding
    tests for the legacy layer moved to
    test_autoresearch.py::TestAutoresearchIntegration. Kept here
    for back-compat verification of the archive path.
    """

    def test_chat_routes_archived_does_not_import_interfaces(self) -> None:
        # 2026-06-19: chat_legacy/routes.py moved to
        # apps/chat/research_engine/routes.py. Verify that new location.
        from pathlib import Path
        src = Path(
            "src/llmwikify/apps/chat/research_engine/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces" not in src

    def test_chat_routes_stores_deps(self) -> None:
        """set_autoresearch_deps should store all deps."""
        from llmwikify.apps.chat.research_engine.routes import set_autoresearch_deps
        set_autoresearch_deps(
            db=None, wiki_registry=None,
            llm_client=None, config=None,
        )


# ─── Architecture contracts ─────────────────────────────────────


class TestArchitectureContracts:
    """Verify layered architecture rules are respected."""

    def test_no_l3_to_l4_imports(self) -> None:
        """apps/ (L3) must never import from interfaces/ (L4)."""
        from pathlib import Path
        apps_dir = Path("src/llmwikify/apps")

        for f in apps_dir.rglob("*.py"):
            if f.name.startswith("__"):
                continue
            lines = f.read_text().splitlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "from llmwikify.interfaces" in line:
                    pytest.fail(
                        f"L3→L4 import detected: {f}:{i}: {stripped}"
                    )
                if "import llmwikify.interfaces" in line:
                    pytest.fail(
                        f"L3→L4 import detected: {f}:{i}: {stripped}"
                    )

    def test_agent_providers_uses_chat_providers(self) -> None:
        """Phase 4 fix: AgentService (apps/chat/agent/agent_service.py)
        imports from apps.chat or apps.db (the new homes), not the
        (deleted) apps.agent.providers."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/apps/chat/agent/agent_service.py"
        ).read_text()
        # AgentService must import from L3 apps layer, not from itself
        has_chat_import = "from llmwikify.apps.chat" in src
        has_db_import = "from llmwikify.apps.db" in src
        assert has_chat_import or has_db_import, (
            "AgentService should import from apps.chat or apps.db"
        )
        assert "from ..providers" not in src


# ─── Phase 4.3 — Rate limit middleware (v0.36) ─────────────────────


class TestGetClientIP:
    """Unit tests for get_client_ip() — Phase 4.3 enhancement.

    Covers:
      - Default (no trusted proxies) → direct TCP peer
      - Trusted proxy with X-Forwarded-For chain
      - Peer not trusted → X-Forwarded-For is ignored (anti-spoof)
      - CIDR network matching
      - No client → "unknown"
    """

    # ── helpers ─────────────────────────────────────────────────

    @staticmethod
    def _make_request(
        peer_ip: str,
        forwarded_for: str | None = None,
    ):
        from unittest.mock import MagicMock

        req = MagicMock()
        req.client.host = peer_ip
        req.client.port = 54321
        headers = {}
        if forwarded_for is not None:
            headers["X-Forwarded-For"] = forwarded_for
        req.headers = headers
        return req

    # ── no trusted proxies ──────────────────────────────────────

    def test_no_trusted_proxies_returns_peer(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=[]):
            req = self._make_request("203.0.113.5")
            assert get_client_ip(req) == "203.0.113.5"

            req2 = self._make_request("203.0.113.5", "10.0.0.1")
            assert get_client_ip(req2) == "203.0.113.5"

    # ── peer not trusted ────────────────────────────────────────

    def test_peer_not_trusted_ignores_xff(self):
        from llmwikify.interfaces.server.http.middleware import (
            _ip_is_trusted,
            get_client_ip,
        )
        trusted = ["127.0.0.1"]
        req = self._make_request("203.0.113.5", "10.0.0.1")

        assert _ip_is_trusted("203.0.113.5", trusted) is False
        assert get_client_ip(req) == "203.0.113.5"

    def test_malicious_xff_from_untrusted_peer(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["127.0.0.1"]):
            req = self._make_request("203.0.113.5", "10.0.0.1")
            assert get_client_ip(req) == "203.0.113.5"

    # ── trusted peer ────────────────────────────────────────────

    def test_trusted_peer_no_xff_returns_peer(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["127.0.0.1"]):
            req = self._make_request("127.0.0.1")
            assert get_client_ip(req) == "127.0.0.1"

    def test_trusted_peer_single_forwarded_ip(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["127.0.0.1"]):
            req = self._make_request("127.0.0.1", "198.51.100.10")
            assert get_client_ip(req) == "198.51.100.10"

    def test_trusted_peer_xff_chain_rightmost_untrusted(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["10.0.0.0/8", "192.168.0.0/16"]):
            req = self._make_request("10.0.0.1", "198.51.100.1, 192.168.1.1, 10.0.0.5")
            assert get_client_ip(req) == "198.51.100.1"

    def test_all_ips_trusted_returns_leftmost(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["10.0.0.0/8", "192.168.0.0/16"]):
            req = self._make_request("10.0.0.1", "192.168.1.1, 10.0.0.2")
            result = get_client_ip(req)
            assert result == "192.168.1.1"

    # ── CIDR matching ───────────────────────────────────────────

    def test_cidr_network_matching(self):
        from llmwikify.interfaces.server.http.middleware import (
            _ip_is_trusted,
            get_client_ip,
        )
        trusted = ["10.0.0.0/8"]
        assert _ip_is_trusted("10.1.2.3", trusted) is True
        assert _ip_is_trusted("10.255.255.255", trusted) is True
        assert _ip_is_trusted("11.0.0.1", trusted) is False

        from unittest.mock import patch
        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["10.0.0.0/8"]):
            req = self._make_request("10.1.2.3", "198.51.100.10")
            assert get_client_ip(req) == "198.51.100.10"

    def test_invalid_ip_in_xff_skipped(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["10.0.0.0/8"]):
            req = self._make_request("10.0.0.1", "not-an-ip, 198.51.100.10, 10.0.0.2")
            result = get_client_ip(req)
            assert result == "198.51.100.10"

    # ── edge cases ──────────────────────────────────────────────

    def test_no_client_returns_unknown(self):
        from unittest.mock import MagicMock

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        req = MagicMock()
        req.client = None
        req.headers = {}
        assert get_client_ip(req) == "unknown"

    def test_xff_empty_string_returns_peer(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["127.0.0.1"]):
            req = self._make_request("127.0.0.1", "")
            assert get_client_ip(req) == "127.0.0.1"

    # ── _ip_is_trusted ──────────────────────────────────────────

    def test_ip_is_trusted_invalid_ip_returns_false(self):
        from llmwikify.interfaces.server.http.middleware import _ip_is_trusted
        assert _ip_is_trusted("not-an-ip", ["127.0.0.1"]) is False
        assert _ip_is_trusted("", ["127.0.0.1"]) is False

    def test_ip_is_trusted_invalid_network_skipped(self):
        from llmwikify.interfaces.server.http.middleware import _ip_is_trusted
        trusted = ["not-a-network", "127.0.0.1"]
        assert _ip_is_trusted("127.0.0.1", trusted) is True
        assert _ip_is_trusted("10.0.0.1", trusted) is False

    # ── ipv6 ────────────────────────────────────────────────────

    def test_ipv6_trusted_proxy(self):
        from unittest.mock import patch

        from llmwikify.interfaces.server.http.middleware import get_client_ip

        with patch("llmwikify.interfaces.server.http.middleware._get_trusted_proxies", return_value=["::1"]):
            req = self._make_request("::1", "2001:db8::1")
            assert get_client_ip(req) == "2001:db8::1"

    def test_ipv6_cidr_matching(self):
        from llmwikify.interfaces.server.http.middleware import _ip_is_trusted
        trusted = ["2001:db8::/32"]
        assert _ip_is_trusted("2001:db8::1", trusted) is True
        assert _ip_is_trusted("2001:db8:ffff::1", trusted) is True
        assert _ip_is_trusted("2001:db9::1", trusted) is False


class TestRateLimitMiddleware:
    """Phase 4.3 (v0.36): verify RateLimitMiddleware import
    and basic construction."""

    def test_import(self) -> None:
        from llmwikify.interfaces.server.http.middleware import (
            RateLimitMiddleware,
        )
        assert RateLimitMiddleware is not None

    def test_construction(self) -> None:
        from llmwikify.interfaces.server.http.middleware import (
            RateLimitMiddleware,
        )
        # Pass a dummy app (just needs to be truthy)
        mw = RateLimitMiddleware(app=lambda: None, limit_per_min=60)
        assert mw.limit_per_min == 60

    def test_disabled_when_zero(self) -> None:
        from llmwikify.interfaces.server.http.middleware import (
            RateLimitMiddleware,
        )
        mw = RateLimitMiddleware(app=lambda: None, limit_per_min=0)
        assert mw.limit_per_min == 0

    @staticmethod
    def _make_mw(limit_per_min: int = 60):
        from llmwikify.interfaces.server.http.middleware import (
            RateLimitMiddleware,
        )
        return RateLimitMiddleware(app=lambda: None, limit_per_min=limit_per_min)

    def test_bucket_creation(self) -> None:
        mw = self._make_mw()
        tokens, last_refill = mw._get_or_create_bucket("203.0.113.5")
        assert tokens == 60.0
        assert last_refill > 0

    def test_bucket_reuses_existing(self) -> None:
        mw = self._make_mw()
        b1 = mw._get_or_create_bucket("203.0.113.5")
        b2 = mw._get_or_create_bucket("203.0.113.5")
        assert b1 is b2

    def test_lru_eviction(self) -> None:
        mw = self._make_mw()
        mw._max_buckets = 3
        mw._get_or_create_bucket("10.0.0.1")
        mw._get_or_create_bucket("10.0.0.2")
        mw._get_or_create_bucket("10.0.0.3")
        assert len(mw._buckets) == 3
        mw._get_or_create_bucket("10.0.0.1")
        mw._get_or_create_bucket("10.0.0.4")
        assert len(mw._buckets) == 3
        assert "10.0.0.1" in mw._buckets
        assert "10.0.0.2" not in mw._buckets
        assert "10.0.0.3" in mw._buckets
        assert "10.0.0.4" in mw._buckets

    @staticmethod
    def _async_ok_response():
        """Return an async call_next that returns a 200 response."""
        from unittest.mock import MagicMock
        async def _inner(req):
            return MagicMock(status_code=200)
        return _inner

    def test_token_refill(self) -> None:
        import time
        mw = self._make_mw()
        now = time.monotonic()
        mw._buckets["203.0.113.5"] = (0.0, now - 60.0)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.client.host = "203.0.113.5"
        req.url.path = "/api/agent/chat"
        req.headers = {}

        import asyncio
        resp = asyncio.run(mw.dispatch(req, self._async_ok_response()))
        assert resp.status_code != 429, "should have been refilled"
        tokens = mw._buckets["203.0.113.5"][0]
        assert tokens >= 58.0, f"expected refilled tokens >= 58, got {tokens}"

    def test_rate_limit_exceeded(self) -> None:
        import time
        mw = self._make_mw(1)
        now = time.monotonic()
        mw._buckets["203.0.113.5"] = (0.0, now)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.client.host = "203.0.113.5"
        req.url.path = "/api/agent/chat"
        req.headers = {}

        import asyncio
        resp = asyncio.run(mw.dispatch(req, self._async_ok_response()))
        assert resp.status_code == 429
        body = resp.body.decode()
        assert "Rate limit exceeded" in body

    def test_non_agent_route_not_limited(self) -> None:
        mw = self._make_mw(1)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.client.host = "203.0.113.5"
        req.url.path = "/api/health"
        req.headers = {}

        import asyncio
        resp = asyncio.run(mw.dispatch(req, self._async_ok_response()))
        assert resp.status_code == 200
        assert "203.0.113.5" not in mw._buckets

    def test_disabled_passes_through(self) -> None:
        mw = self._make_mw(0)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.client.host = "203.0.113.5"
        req.url.path = "/api/agent/chat"

        import asyncio
        resp = asyncio.run(mw.dispatch(req, self._async_ok_response()))
        assert resp.status_code == 200

    def test_tokens_consumed_on_success(self) -> None:
        import time
        mw = self._make_mw()
        now = time.monotonic()
        mw._buckets["203.0.113.5"] = (60.0, now)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.client.host = "203.0.113.5"
        req.url.path = "/api/agent/chat"
        req.headers = {}

        import asyncio
        resp = asyncio.run(mw.dispatch(req, self._async_ok_response()))
        assert resp.status_code != 429
        remaining = mw._buckets["203.0.113.5"][0]
        assert remaining == 59.0, f"expected 59.0 remaining, got {remaining}"

    def test_retry_after_header_present(self) -> None:
        import time
        mw = self._make_mw(1)
        now = time.monotonic()
        mw._buckets["203.0.113.5"] = (0.0, now)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.client.host = "203.0.113.5"
        req.url.path = "/api/agent/chat"
        req.headers = {}

        import asyncio
        resp = asyncio.run(mw.dispatch(req, self._async_ok_response()))
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
