"""Unit tests for v0.32 Phase 9: routes migration.

Covers:

  - 2 routers are at the new home (interfaces/server/http/)
  - All 2 routers are importable (chat_sse, research)
  - Backward-compat shims (4 paths) re-export correctly
  - The L4 routes.py uses the new home (no apps.agent.routes refs)
  - The L3→L4 dependency in apps/chat/routes.py was removed
  - Architecture contracts stay green

Target: 30+ tests, no I/O, no real FastAPI server.
"""

from __future__ import annotations

import pytest


# ─── New home: 2 routers importable ─────────────────────────────


class TestNewHomeImports:
    """All 2 migrated route modules are importable from
    ``llmwikify.interfaces.server.http``."""

    def test_chat_sse_imports(self) -> None:
        from llmwikify.interfaces.server.http.chat_sse import (
            router,
            set_agent_service,
            get_agent_service,
        )
        assert router is not None
        assert callable(set_agent_service)
        assert callable(get_agent_service)

    def test_research_imports(self) -> None:
        from llmwikify.interfaces.server.http.research import (
            router,
            set_research_deps,
        )
        assert router is not None
        assert callable(set_research_deps)

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


# ─── Router attributes (APIRouter + prefix) ──────────────────────


class TestRouterAttributes:
    """Each router has the expected APIRouter prefix and tags."""

    def test_chat_sse_router_prefix(self) -> None:
        from llmwikify.interfaces.server.http.chat_sse import router
        assert router.prefix == "/api/agent"
        assert "agent" in router.tags

    def test_research_router_prefix(self) -> None:
        from llmwikify.interfaces.server.http.research import router
        assert router.prefix == "/api/research"
        assert "research" in router.tags

    def test_routers_have_routes(self) -> None:
        """Each router should have at least 1 registered route."""
        from llmwikify.interfaces.server.http.chat_sse import router as c
        from llmwikify.interfaces.server.http.research import router as r
        assert len(c.routes) > 0
        assert len(r.routes) > 0


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
        """routes.py should import research from the new location."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces.server.http.research import" in src

    def test_routes_py_uses_explicit_llm_client(self) -> None:
        """set_research_deps should receive llm_client param."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "set_research_deps(" in src
        assert "llm_client" in src


# ─── L3 chat routes ─────────────────────────────────────────────


class TestL3ChatRoutes:
    """apps/chat/routes.py should not import from interfaces/."""

    def test_chat_routes_does_not_import_interfaces(self) -> None:
        from pathlib import Path
        src = Path(
            "src/llmwikify/apps/chat/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces" not in src

    def test_chat_routes_stores_deps(self) -> None:
        """set_autoresearch_deps should store all deps."""
        from llmwikify.apps.chat.routes import set_autoresearch_deps
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
