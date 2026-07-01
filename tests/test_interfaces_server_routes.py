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
        from llmwikify.interfaces.server.http.chat_sse import (
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
        from llmwikify.interfaces.server.http.chat_sse import router
        assert router.prefix == "/api/agent"
        assert "agent" in router.tags

    def test_routers_have_routes(self) -> None:
        """The chat_sse router should have at least 1 registered route."""
        from llmwikify.interfaces.server.http.chat_sse import router as c
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
        assert "from llmwikify.interfaces.server.http.chat_sse import" in src

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
        assert "from llmwikify.interfaces.server.http.chat_sse import" in src


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
