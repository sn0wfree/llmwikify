"""FastAPI route definitions - unified single and multi-wiki mode."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from llmwikify.apps.chat.channels.websocket import _register_websocket_routes
from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.instance import WikiType
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

logger = logging.getLogger(__name__)



def register_routes(
    app: FastAPI,
    registry: WikiRegistry,
    provider: Any = None,
    *,
    api_key: str | None = None,
) -> None:
    """Register all API routes (unified architecture).

    Args:
        app: FastAPI application
        registry: WikiRegistry (always created, even for single wiki)
        provider: optional LLM client (Phase 7). Forwarded to
            ``_register_agent_routes`` so AgentService can wire it
            into MemoryManager for Consolidator + Dream.
        api_key
            Optional API key (Phase 14, WS auth). Forwarded to
            ``_register_websocket_routes`` so the WebSocket
            handshake can validate ``?token=`` against the same
            key as the REST ``AuthMiddleware``. Pass ``None`` to
            disable WS auth (dev mode).

    Phase 19-B: also wires the ``AgentService`` (created by
    ``_register_agent_routes``) into the WS router so the
    ``message`` handler routes to the real ``ChatOrchestrator``
    instead of echoing.
    """
    _register_wiki_routes(app, registry, provider=provider)
    _register_agent_routes(app, registry, provider=provider)
    # Phase 19-B: pass the freshly-created AgentService so the WS
    # handler can route ``message`` to ChatOrchestrator.chat(). We
    # resolve via the global set by ``_register_agent_routes`` →
    # ``chat_sse.set_agent_service`` to avoid refactoring its
    # private signature.
    from llmwikify.interfaces.server.http.chat_sse import get_agent_service
    agent_svc = None
    try:
        agent_svc = get_agent_service()
    except RuntimeError:
        # Agent service not initialized — WS falls back to echo
        pass
    _register_websocket_routes(
        app, api_key=api_key or "", chat_service=agent_svc,
    )


def _register_wiki_routes(
    app: FastAPI,
    registry: WikiRegistry,
    provider: Any = None,
) -> None:
    """Register unified wiki routes with WikiRegistry."""

    def _get_default_or_first_wiki_id() -> str:
        """Get default wiki_id or first registered wiki if only one exists."""
        default_id = registry.get_default_wiki_id()
        if default_id:
            return default_id
        wikis = registry.list_wikis()
        if len(wikis) == 1:
            return wikis[0].wiki_id
        elif len(wikis) == 0:
            raise HTTPException(status_code=400, detail="No wiki registered")
        raise HTTPException(status_code=400, detail="No default wiki configured")

    def get_wiki_by_id(wiki_id: str) -> Wiki:
        instance = registry.get_wiki_instance(wiki_id)
        if instance.wiki_type == WikiType.REMOTE:
            raise HTTPException(status_code=400, detail="Cannot access remote wiki directly")
        return registry.get_wiki(wiki_id)

    def get_wiki() -> Wiki:
        wiki_id = _get_default_or_first_wiki_id()
        return registry.get_wiki(wiki_id)

    # --- Wiki Management Routes ---
    wiki_router = APIRouter(prefix="/api/wiki", tags=["wiki"])

    @wiki_router.get("/status")
    async def wiki_status(wiki: Wiki = Depends(get_wiki)):
        """Get wiki status summary."""
        status = wiki.status()
        if "pages_by_type" in status:
            status["all_types"] = list(status["pages_by_type"].keys())
        return status

    @wiki_router.get("/search")
    async def wiki_search(q: str, limit: int = 10, backend: str = "fts5", wiki: Wiki = Depends(get_wiki)):
        """Full-text search across wiki pages."""
        return wiki.search(q, limit, backend=backend)

    @wiki_router.get("/page/{page_name:path}")
    async def wiki_read_page(page_name: str, wiki: Wiki = Depends(get_wiki)):
        """Read a wiki page."""
        try:
            page_data = wiki.read_page(page_name)
            if isinstance(page_data, dict) and "error" in page_data:
                raise HTTPException(status_code=404, detail=page_data["error"])
            sink_info = wiki.query_sink.get_info_for_page(page_name)
            if isinstance(page_data, dict):
                return {**page_data, **sink_info}
            return page_data
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @wiki_router.post("/page")
    async def wiki_write_page(request: Request, wiki: Wiki = Depends(get_wiki)):
        """Write a wiki page."""
        body = await request.json()
        page_name = body.get("page_name", "")
        content = body.get("content", "")
        if not page_name:
            raise HTTPException(status_code=400, detail="page_name required")
        result = wiki.write_page(page_name, content)
        return {"message": result, "page_name": page_name}

    @wiki_router.get("/sink/status")
    async def wiki_sink_status(wiki: Wiki = Depends(get_wiki)):
        """Get sink buffer status."""
        return wiki.sink_status()

    @wiki_router.get("/lint")
    async def wiki_lint(
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        wiki: Wiki = Depends(get_wiki),
    ):
        """Health-check the wiki."""
        return wiki.lint(mode=mode, limit=limit, force=force)

    @wiki_router.get("/recommend")
    async def wiki_recommend(wiki: Wiki = Depends(get_wiki)):
        """Get wiki recommendations."""
        return wiki.recommend()

    @wiki_router.get("/suggest_synthesis")
    async def wiki_suggest_synthesis(source_name: str | None = None, wiki: Wiki = Depends(get_wiki)):
        """Get cross-source synthesis suggestions."""
        return wiki.suggest_synthesis(source_name=source_name)

    @wiki_router.get("/graph_analyze")
    async def wiki_graph_analyze(wiki: Wiki = Depends(get_wiki)):
        """Analyze knowledge graph structure."""
        return wiki.graph_analyze()

    @wiki_router.get("/graph")
    async def wiki_graph(
        current_page: str | None = None,
        mode: str = "auto",
        wiki: Wiki = Depends(get_wiki),
    ):
        """Return graph data optimized for visualization."""
        from llmwikify.kernel.graph.visualizer import build_visualization_data
        return build_visualization_data(wiki.index, wiki, current_page, mode)

    app.include_router(wiki_router)

    # --- Wiki Management Routes ---
    wikis_router = APIRouter(prefix="/api/wikis", tags=["wikis"])

    @wikis_router.get("")
    async def list_wikis():
        """List all registered wikis."""
        wikis = registry.list_wikis()
        return {
            "wikis": [w.to_dict() for w in wikis],
            "default_wiki_id": registry.get_default_wiki_id(),
        }

    @wikis_router.post("")
    async def register_wiki(request: Request):
        """Register a new wiki."""
        body = await request.json()
        wiki_id = body.get("wiki_id")
        name = body.get("name", wiki_id)
        wiki_type = body.get("type", "local")

        if not wiki_id:
            raise HTTPException(status_code=400, detail="wiki_id required")

        if wiki_type == "remote":
            url = body.get("url")
            if not url:
                raise HTTPException(status_code=400, detail="url required for remote wiki")
            instance = registry.register_remote(
                wiki_id=wiki_id,
                name=name,
                url=url,
                api_key=body.get("api_key"),
                timeout=body.get("timeout", 30),
                verify_ssl=body.get("verify_ssl", True),
            )
        else:
            root = body.get("root")
            if not root:
                raise HTTPException(status_code=400, detail="root required for local wiki")
            from pathlib import Path
            instance = registry.register_wiki(
                wiki_id=wiki_id,
                name=name,
                root=Path(root),
            )

        return instance.to_dict()

    @wikis_router.get("/{wiki_id}")
    async def get_wiki_info(wiki_id: str):
        """Get wiki details."""
        try:
            instance = registry.get_wiki_instance(wiki_id)
            return instance.to_dict()
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wikis_router.put("/{wiki_id}")
    async def update_wiki(wiki_id: str, request: Request):
        """Update wiki configuration."""
        body = await request.json()
        try:
            instance = registry.get_wiki_instance(wiki_id)
            # Update allowed fields
            if "name" in body:
                instance.name = body["name"]
            if "is_default" in body and body["is_default"]:
                registry.set_default_wiki(wiki_id)
            return instance.to_dict()
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wikis_router.delete("/{wiki_id}")
    async def unregister_wiki(wiki_id: str):
        """Unregister a wiki."""
        try:
            registry.unregister_wiki(wiki_id)
            return {"message": f"Wiki {wiki_id} unregistered"}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wikis_router.post("/{wiki_id}/reload")
    async def reload_wiki(wiki_id: str):
        """Reload/re-index a wiki."""
        result = registry.reload_wiki(wiki_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message"))
        return result

    @wikis_router.get("/{wiki_id}/health")
    async def wiki_health(wiki_id: str):
        """Check wiki health."""
        try:
            status = registry.get_wiki_status(wiki_id)
            return status
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @wikis_router.post("/scan")
    async def scan_wikis(request: Request):
        """Trigger directory scan for wikis."""
        body = await request.json()
        scan_paths = body.get("scan_paths", ["."])
        scan_depth = body.get("scan_depth", 2)
        new_wikis = registry.scan_directories(scan_paths, scan_depth)
        return {
            "new_wikis": [w.to_dict() for w in new_wikis],
            "count": len(new_wikis),
        }

    app.include_router(wikis_router)

    # --- Wiki-Scoped Routes ---

    wiki_router = APIRouter(prefix="/api/wiki", tags=["wiki"])

    @wiki_router.get("/{wiki_id}/status")
    async def wiki_status_by_id(wiki_id: str):
        """Get wiki status by ID."""
        try:
            status = registry.get_wiki_status(wiki_id)
            if "pages_by_type" in status:
                status["all_types"] = list(status["pages_by_type"].keys())
            return status
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/pages")
    async def wiki_pages_by_id(wiki_id: str):
        """Get list of all pages in a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            page_names = wiki._get_existing_page_names()
            return {"pages": page_names, "count": len(page_names)}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/search")
    async def wiki_search_by_id(wiki_id: str, q: str, limit: int = 10, backend: str = "fts5"):
        """Search within a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            return wiki.search(q, limit, backend=backend)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/page/{page_name:path}")
    async def wiki_read_page_by_id(wiki_id: str, page_name: str):
        """Read a page from a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            page_data = wiki.read_page(page_name)
            if isinstance(page_data, dict) and "error" in page_data:
                raise HTTPException(status_code=404, detail=page_data["error"])
            sink_info = wiki.query_sink.get_info_for_page(page_name)
            if isinstance(page_data, dict):
                return {**page_data, **sink_info}
            return page_data
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @wiki_router.post("/{wiki_id}/page")
    async def wiki_write_page_by_id(wiki_id: str, request: Request):
        """Write a page to a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            body = await request.json()
            page_name = body.get("page_name", "")
            content = body.get("content", "")
            if not page_name:
                raise HTTPException(status_code=400, detail="page_name required")
            result = wiki.write_page(page_name, content)
            return {"message": result, "page_name": page_name}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/lint")
    async def wiki_lint_by_id(
        wiki_id: str,
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
    ):
        """Health-check a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            return wiki.lint(mode=mode, limit=limit, force=force)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/recommend")
    async def wiki_recommend_by_id(wiki_id: str):
        """Get recommendations for a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            return wiki.recommend()
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/graph")
    async def wiki_graph_by_id(
        wiki_id: str,
        current_page: str | None = None,
        mode: str = "auto",
    ):
        """Get graph data for a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            from llmwikify.kernel.graph.visualizer import build_visualization_data
            return build_visualization_data(wiki.index, wiki, current_page, mode)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    @wiki_router.get("/{wiki_id}/sink/status")
    async def wiki_sink_status_by_id(wiki_id: str):
        """Get sink buffer status for a specific wiki."""
        try:
            wiki = get_wiki_by_id(wiki_id)
            return wiki.sink_status()
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Wiki not found: {wiki_id}")

    # Legacy fallback routes (backward compatible - use default wiki)
    @wiki_router.get("/status")
    async def wiki_status_legacy():
        """Get wiki status (legacy - uses default wiki)."""
        if not registry.get_default_wiki_id():
            raise HTTPException(status_code=400, detail="No default wiki configured")
        return await wiki_status_by_id(registry.get_default_wiki_id())

    @wiki_router.get("/search")
    async def wiki_search_legacy(q: str, limit: int = 10, backend: str = "fts5"):
        """Search wiki (legacy - uses default wiki)."""
        if not registry.get_default_wiki_id():
            raise HTTPException(status_code=400, detail="No default wiki configured")
        return await wiki_search_by_id(registry.get_default_wiki_id(), q, limit, backend)

    app.include_router(wiki_router)

    # --- Cross-Wiki Search ---

    search_router = APIRouter(prefix="/api/search", tags=["search"])

    @search_router.get("/cross")
    async def cross_wiki_search(
        q: str,
        limit: int = 10,
        wikis: str | None = None,
        backend: str = "fts5",
    ):
        """Search across multiple wikis.

        Args:
            q: Search query
            limit: Results per wiki
            wikis: Comma-separated wiki IDs (empty = all)
            backend: Search backend
        """
        wiki_ids = wikis.split(",") if wikis else None
        results = registry.cross_wiki_search(q, wiki_ids, limit)
        return {
            "results": results,
            "total_results": len(results),
            "searched_wikis": wiki_ids or [w.wiki_id for w in registry.list_wikis()],
        }

    app.include_router(search_router)

    # --- Client Error Logging ---
    log_router = APIRouter(tags=["log"])
    _log_logger = logging.getLogger("client.errors")

    @log_router.post("/api/log/error")
    async def log_client_error(request: Request):
        """Receive frontend error reports and write to server log."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        err_type = body.get("type", "unknown")
        message = body.get("message", "")
        url = body.get("url", "")
        filename = body.get("filename", "")
        lineno = body.get("lineno", "")
        colno = body.get("colno", "")
        stack = body.get("stack", "")
        status = body.get("status", "")
        method = body.get("method", "")
        req_body = body.get("requestBody", "")
        content_type = body.get("contentType", "")
        body_snippet = body.get("bodySnippet", "")
        endpoint = body.get("endpoint", "")
        client_ip = request.client.host if request.client else "unknown"

        if err_type == "api-error":
            parts = [f"[api-error] {method} {url} → {status}"]
            if content_type:
                parts.append(f"resp-ct={content_type}")
            if client_ip:
                parts.append(f"client={client_ip}")
            _log_logger.error(" | ".join(parts))
            if req_body:
                _log_logger.error(f"  req-body: {req_body}")
            if body_snippet:
                _log_logger.error(f"  resp-body: {body_snippet[:500]}")
        elif err_type == "fetch-error":
            parts = [f"[fetch-error] {method} {endpoint}"]
            if message:
                parts.append(f"err={message[:200]}")
            if client_ip:
                parts.append(f"client={client_ip}")
            _log_logger.error(" | ".join(parts))
        else:
            parts = [f"[{err_type}] {message}"]
            if url:
                parts.append(f"url={url}")
            if filename:
                parts.append(f"file={filename}:{lineno}:{colno}")
            if client_ip:
                parts.append(f"client={client_ip}")
            _log_logger.error(" | ".join(parts))
            if stack:
                _log_logger.error(f"Stack: {stack[:2000]}")
        return {"ok": True}

    app.include_router(log_router)

    # --- Agent Routes (Phase 7: provider forwarded to MemoryManager) ---
    _register_agent_routes(app, registry, provider=provider)

    # --- Skills introspection (Phase 11-F2) ---
    # Surfaces registered skills + their plugin frontmatter
    # (version / author / triggers / tags) so the webui and operators
    # can introspect what's loaded without grepping logs.
    _register_skills_routes(app)


def _load_research_config() -> dict[str, Any] | None:
    """Load research config from global config file (~/.llmwikify/llmwikify.json).

    Reads the "research" section if present. Returns None if file doesn't exist.
    """
    import json as _json

    config_file = Path.home() / ".llmwikify" / "llmwikify.json"
    if not config_file.exists():
        return None
    try:
        data = _json.loads(config_file.read_text())
        return data.get("research")
    except Exception:
        return None


def _register_agent_routes(
    app: FastAPI,
    registry: WikiRegistry,
    provider: Any = None,
) -> None:
    """Register Agent backend routes (Phase 1).

    Phase 7 (2026-06-19): Accepts an optional ``provider`` (LLM client)
    so the AgentService wires it into MemoryManager, enabling the
    Phase 6 Consolidator + Dream pipeline. If ``provider`` is None,
    the existing fallback path (provider-less MemoryManager) is used.

    Phase 19-D (2026-06-22): ``data_dir`` honors ``LLMWIKIFY_DATA_DIR``
    when set, falling back to ``~/.llmwikify/agent``. This lets tests
    monkeypatch the data dir via ``monkeypatch.setenv`` without writing
    to the production database (which ``Path.home()`` ignores on Linux).
    """
    from llmwikify.apps.chat.agent.agent_service import AgentService
    from llmwikify.interfaces.server.http.chat_sse import set_agent_service

    # Phase 19-D: prefer explicit LLMWIKIFY_DATA_DIR; fall back to
    # the previous ``~/.llmwikify/agent`` default. Without this,
    # pytest's ``monkeypatch.setenv("HOME", ...)`` had no effect
    # (``Path.home()`` consults /etc/passwd, not $HOME), so test
    # runs polluted the real production DB with mock-LLM fixtures.
    _env_data_dir = os.environ.get("LLMWIKIFY_DATA_DIR")
    if _env_data_dir:
        data_dir = Path(_env_data_dir)
    else:
        data_dir = Path.home() / ".llmwikify" / "agent"
    data_dir.mkdir(parents=True, exist_ok=True)

    agent_service = AgentService(registry, data_dir, provider=provider)
    set_agent_service(agent_service)

    # Register /api/autoresearch/* routes (router exists, never mounted)
    from llmwikify.apps.chat.config import merge_six_step_config
    from llmwikify.apps.chat.research_engine.routes import (
        router as autoresearch_router,
        set_autoresearch_deps,
    )

    db = agent_service.app_db.chat
    set_autoresearch_deps(
        db=db,
        wiki_registry=registry,
        llm_client=provider,
        config=merge_six_step_config(),
        tool_registry=agent_service._get_tool_registry(),
    )
    app.include_router(autoresearch_router)

    from llmwikify.interfaces.server.http.chat_sse import router as agent_router

    app.include_router(agent_router)

    # P1-1 (vendored from nanobot api/server.py):
    # OpenAI-compatible /v1/chat/completions + /v1/models + /v1/health.
    # L3-local: openai_server.py maintains its own agent_service registry
    # (no L3→L4 import); routes.py sets it explicitly here.
    from llmwikify.apps.api.openai_server import (
        create_openai_router,
    )
    from llmwikify.apps.api.openai_server import (
        set_agent_service as set_openai_agent_service,
    )

    set_openai_agent_service(agent_service)

    model_name = "llmwikify-chat"
    try:
        from llmwikify.apps.chat.providers.registry import get_default_provider
        provider = get_default_provider()
        if provider and getattr(provider, "model", None):
            model_name = provider.model
    except Exception:
        pass
    app.include_router(create_openai_router(model=model_name))

    _register_reproduction_routes(app, registry, agent_service, data_dir=data_dir)

    _mount_agent_spa(app)


def _register_skills_routes(app: FastAPI) -> None:
    """Phase 11-F2: expose registered skills + plugin metadata.

    Two endpoints, both mounted under ``/api/skills``:

      - ``GET /api/skills``         — list all registered skills with
        their manifests (name / description / actions) and any plugin
        frontmatter (version / author / tags / license / source).
      - ``GET /api/skills/{name}``  — single skill detail.

    Skills that were registered through ``PromptBasedSkill`` plugin
    files (``~/.llmwikify/skills/<name>/SKILL.md``) carry an extra
    ``_plugin_metadata`` dict populated by ``plugin_loader``; those
    fields are surfaced as ``plugin.*`` in the response. Built-in
    skills don't have plugin metadata, so those keys are simply absent
    — callers should use ``.get('plugin')`` defensively.
    """
    from llmwikify.apps.chat.skills.registry import default_registry

    skills_router = APIRouter(prefix="/api/skills", tags=["skills"])

    @skills_router.get("")
    async def list_skills() -> dict[str, Any]:
        """List all registered skills with action summaries + plugin metadata."""
        registry = default_registry()
        out: list[dict[str, Any]] = []
        for skill in registry:
            entry: dict[str, Any] = {
                "name": skill.name,
                "description": skill.description,
                "action_count": len(skill.actions),
                "actions": sorted(skill.actions.keys()),
            }
            plugin_meta = getattr(skill, "_plugin_metadata", None)
            if plugin_meta:
                entry["plugin"] = plugin_meta
            out.append(entry)
        return {"count": len(out), "skills": out}

    @skills_router.get("/{name}")
    async def get_skill(name: str) -> dict[str, Any]:
        """Detail for a single skill; 404 if not registered."""
        registry = default_registry()
        skill = registry.get(name)
        if skill is None:
            raise HTTPException(
                status_code=404, detail=f"Skill {name!r} not registered"
            )
        manifest = skill.manifest().to_dict()
        entry: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "manifest": manifest,
        }
        plugin_meta = getattr(skill, "_plugin_metadata", None)
        if plugin_meta:
            entry["plugin"] = plugin_meta
        return entry

    app.include_router(skills_router)


def _register_reproduction_routes(
    app: FastAPI,
    registry: WikiRegistry,
    agent_service: Any,
    data_dir: Path | None = None,
) -> None:
    """Register paper/factor/strategy/reproduction routers and inject deps.

    Lives here (not in ``_register_wiki_routes``) because the reproduction
    routers need access to the LLM client and the reproduction session DB
    that the agent service owns. v0.4.0 — end-to-end reproduction pipeline.
    """
    from llmwikify.interfaces.server.http.factor import (
        router as factor_router,
    )
    from llmwikify.interfaces.server.http.factor import (
        set_factor_deps,
    )
    from llmwikify.interfaces.server.http.paper import (
        router as paper_router,
    )
    from llmwikify.interfaces.server.http.paper import (
        set_paper_deps,
    )
    from llmwikify.interfaces.server.http.reproduction import (
        router as reproduction_router,
    )
    from llmwikify.interfaces.server.http.reproduction import (
        set_repro_deps,
    )
    from llmwikify.interfaces.server.http.strategy import (
        router as strategy_router,
    )
    from llmwikify.interfaces.server.http.strategy import (
        set_strategy_deps,
    )
    from llmwikify.reproduction.sessions import ReproductionDatabase

    if data_dir is None:
        data_dir = Path.home() / ".llmwikify" / "agent"
    data_dir.mkdir(parents=True, exist_ok=True)
    repro_db = ReproductionDatabase(data_dir / "reproduction.db")
    logger.info("Reproduction DB initialized at: %s", repro_db.db_path)

    # raw_dir: use the default wiki's raw directory, not the code repo path
    try:
        raw_dir = registry.get_default_wiki().raw_dir
    except Exception:
        raw_dir = Path.home() / ".llmwikify" / "raw"
    upload_dir = raw_dir
    logger.info("paper raw_dir: %s, upload_dir: %s", raw_dir, upload_dir)

    # Read parquet path from config
    try:
        _cfg_file = Path.home() / ".llmwikify" / "llmwikify.json"
        _parquet_path = __import__("json").loads(_cfg_file.read_text()).get("parquet", {}).get("path") if _cfg_file.exists() else None
    except Exception:
        _parquet_path = None

    set_paper_deps(
        wiki_registry=registry,
        llm_client=agent_service._get_llm(),
        db=repro_db,
        raw_dir=raw_dir,
        upload_dir=upload_dir,
        parquet_path=_parquet_path,
    )
    set_factor_deps(
        wiki_registry=registry,
        llm_client=agent_service._get_llm(),
    )
    set_strategy_deps(wiki_registry=registry)
    set_repro_deps(db=repro_db, wiki_registry=registry)

    app.include_router(paper_router)
    app.include_router(factor_router)
    app.include_router(strategy_router)
    app.include_router(reproduction_router)
    logger.info(
        "Reproduction routers registered: paper, factor, strategy, reproduction"
    )


def _mount_agent_spa(app: FastAPI) -> None:
    """Unified SPA handles /agent routes via client-side routing.

    The SPA at ui/webui/dist/ handles both / and /agent routes.
    No separate mount is needed — the SPA's BrowserRouter handles routing.
    """
    pass
