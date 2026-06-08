"""Unit tests for v0.32 Phase 9: routes migration.

Covers:

  - 3 routes are at the new home (interfaces/server/http/)
  - All 3 routers are importable (chat_sse, ppt, research)
  - The ppt_chat_router is still sourced from apps/ppt/chat_routes
    (it's a different L3 module that wraps an L4 endpoint)
  - Backward-compat shims (4 paths) re-export correctly
  - The L4 routes.py uses the new home (no apps.agent.routes refs)
  - The L3→L4 dependency in apps/chat/routes.py was removed
    (set_autoresearch_deps now takes the LLM client explicitly)
  - Architecture contracts stay green

Target: 30+ tests, no I/O, no real FastAPI server.
"""

from __future__ import annotations

import pytest


# ─── New home: 3 routers importable ─────────────────────────────


class TestNewHomeImports:
    """All 3 migrated route modules are importable from
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

    def test_ppt_imports(self) -> None:
        from llmwikify.interfaces.server.http.ppt import (
            router,
            set_ppt_deps,
        )
        assert router is not None
        assert callable(set_ppt_deps)

    def test_research_imports(self) -> None:
        from llmwikify.interfaces.server.http.research import (
            router,
            set_research_deps,
        )
        assert router is not None
        assert callable(set_research_deps)

    def test_ppt_chat_router_sourced_from_ppt_chat_routes(self) -> None:
        """``ppt_chat_router`` is NOT in interfaces/server/http/.
        It stays in apps/ppt/chat_routes.py (its natural home
        for the PPT chat feature)."""
        from llmwikify.apps.ppt.chat_routes import router as ppt_chat_router
        assert ppt_chat_router is not None

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

    def test_ppt_router_prefix(self) -> None:
        from llmwikify.interfaces.server.http.ppt import router
        assert router.prefix == "/api/ppt"
        assert "ppt" in router.tags

    def test_research_router_prefix(self) -> None:
        from llmwikify.interfaces.server.http.research import router
        assert router.prefix == "/api/research"
        assert "research" in router.tags

    def test_routers_have_routes(self) -> None:
        """Each router should have at least 1 registered route."""
        from llmwikify.interfaces.server.http.chat_sse import router as c
        from llmwikify.interfaces.server.http.ppt import router as p
        from llmwikify.interfaces.server.http.research import router as r
        assert len(c.routes) >= 1
        assert len(p.routes) >= 1
        assert len(r.routes) >= 1


# ─── Backward-compat shims ────────────────────────────────────────


class TestBackwardCompatShims:
    """4 shim files at the OLD paths re-export the new homes."""

    def test_shim_routes_agent(self) -> None:
        from llmwikify.agent.backend import routes_agent as shim
        from llmwikify.interfaces.server.http.chat_sse import (
            router, set_agent_service,
        )
        assert shim.router is router
        assert shim.set_agent_service is set_agent_service

    def test_shim_routes_ppt(self) -> None:
        from llmwikify.agent.backend import routes_ppt as shim
        from llmwikify.interfaces.server.http.ppt import (
            router, set_ppt_deps,
        )
        assert shim.router is router
        assert shim.set_ppt_deps is set_ppt_deps

    def test_shim_routes_research(self) -> None:
        from llmwikify.agent.backend import routes_research as shim
        from llmwikify.interfaces.server.http.research import (
            router, set_research_deps,
        )
        assert shim.router is router
        assert shim.set_research_deps is set_research_deps

    def test_shim_routes_package(self) -> None:
        from llmwikify.agent.backend import routes as shim
        from llmwikify.interfaces.server.http import (
            chat_sse, ppt, research,
        )
        assert shim.chat_sse is chat_sse
        assert shim.ppt is ppt
        assert shim.research is research


# ─── L4 routes.py uses new home (not apps.agent.routes) ──────────


class TestL4RoutesPy:
    """interfaces/server/http/routes.py must import from the new home."""

    def test_routes_py_does_not_import_apps_agent_routes(self) -> None:
        """The L4 routes.py should not have any reference to
        ``llmwikify.apps.agent.routes``."""
        import inspect
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        # Negative assertion: no references to the old path
        assert "from llmwikify.apps.agent.routes" not in src
        assert "import llmwikify.apps.agent.routes" not in src

    def test_routes_py_imports_chat_sse_from_new_home(self) -> None:
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces.server.http.chat_sse" in src

    def test_routes_py_imports_ppt_from_new_home(self) -> None:
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces.server.http.ppt" in src

    def test_routes_py_imports_research_from_new_home(self) -> None:
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces.server.http.research" in src

    def test_routes_py_uses_explicit_llm_client(self) -> None:
        """Phase 9 fix: ``set_autoresearch_deps`` is called with
        ``llm_client=agent_service._get_llm()`` (not None)."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/interfaces/server/http/routes.py"
        ).read_text()
        # Search for the line that calls set_autoresearch_deps
        # with llm_client. It should NOT be None anymore.
        assert "llm_client=agent_service._get_llm()" in src


# ─── L3→L4 dependency removal (chat/routes.py) ────────────────────


class TestL3ChatRoutes:
    """apps/chat/routes.py must NOT import from interfaces.server.http.
    The LLM client is now passed explicitly via set_autoresearch_deps."""

    def test_chat_routes_does_not_import_interfaces(self) -> None:
        from pathlib import Path
        src = Path(
            "src/llmwikify/apps/chat/routes.py"
        ).read_text()
        assert "from llmwikify.interfaces.server.http" not in src
        assert "import llmwikify.interfaces.server.http" not in src

    def test_chat_routes_raises_on_missing_llm(self) -> None:
        """The fallback (None LLM) is now an explicit RuntimeError,
        not an L3→L4 import."""
        from llmwikify.apps.chat.routes import set_autoresearch_deps, _get_engine
        from llmwikify.apps.chat.db import AutoResearchDatabase
        import tempfile

        class _MockWiki:
            def get_default_wiki(self):
                return "mock_wiki"

        with tempfile.TemporaryDirectory() as tmp:
            set_autoresearch_deps(
                db=AutoResearchDatabase(tmp),
                wiki_registry=_MockWiki(),
                llm_client=None,
                config={},
            )
            with pytest.raises(RuntimeError, match="LLM client not initialized"):
                _get_engine()


# ─── Architecture contracts ────────────────────────────────────────


class TestArchitectureContracts:
    """The 4-layer architecture must stay green after the migration."""

    def test_no_l3_to_l4_imports(self) -> None:
        """apps/* must NOT import from interfaces.* (no upward)."""
        from pathlib import Path
        for f in Path("src/llmwikify/apps").rglob("*.py"):
            if "__pycache__" in str(f) or "/legacy" in str(f):
                continue
            src = f.read_text()
            # Look for absolute imports of interfaces from inside apps/
            for line in src.split("\n"):
                if "from llmwikify.interfaces" in line:
                    pytest.fail(
                        f"L3→L4 import detected: {f}: {line.strip()}"
                    )

    def test_agent_providers_uses_chat_providers(self) -> None:
        """Phase 4 fix: apps/agent/core/service.py imports
        from apps.chat.providers (the new home), not the
        (deleted) apps.agent.providers."""
        from pathlib import Path
        src = Path(
            "src/llmwikify/apps/agent/core/service.py"
        ).read_text()
        assert "from llmwikify.apps.chat.providers" in src
        assert "from ..providers" not in src


# ─── File structure sanity ────────────────────────────────────────


class TestFileStructure:
    """The new home has the 3 routes, the old home is gone."""

    def test_apps_agent_routes_directory_gone(self) -> None:
        from pathlib import Path
        routes_dir = Path("src/llmwikify/apps/agent/routes")
        assert not routes_dir.exists(), (
            f"old routes dir still exists: {routes_dir}"
        )

    def test_interfaces_server_http_has_3_routes(self) -> None:
        from pathlib import Path
        http_dir = Path("src/llmwikify/interfaces/server/http")
        assert (http_dir / "chat_sse.py").exists()
        assert (http_dir / "ppt.py").exists()
        assert (http_dir / "research.py").exists()
