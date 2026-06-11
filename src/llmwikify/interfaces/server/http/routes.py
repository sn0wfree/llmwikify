"""FastAPI route definitions - unified single and multi-wiki mode."""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from fastapi import APIRouter, FastAPI, Request, HTTPException, Depends
from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.instance import WikiType
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

logger = logging.getLogger(__name__)



def register_routes(
    app: FastAPI,
    registry: WikiRegistry,
) -> None:
    """Register all API routes (unified architecture).

    Args:
        app: FastAPI application
        registry: WikiRegistry (always created, even for single wiki)
    """
    _register_wiki_routes(app, registry)


def _register_wiki_routes(app: FastAPI, registry: WikiRegistry) -> None:
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

    # --- Agent Routes ---
    _register_agent_routes(app, registry)


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


def _register_agent_routes(app: FastAPI, registry: WikiRegistry) -> None:
    """Register Agent backend routes (Phase 1)."""
    from llmwikify.apps.chat.agent.agent_service import AgentService
    from llmwikify.interfaces.server.http.chat_sse import set_agent_service

    data_dir = Path.home() / ".llmwikify" / "agent"
    data_dir.mkdir(parents=True, exist_ok=True)

    agent_service = AgentService(registry, data_dir)
    set_agent_service(agent_service)

    from llmwikify.interfaces.server.http.chat_sse import router as agent_router
    from llmwikify.apps.chat.routes import set_autoresearch_deps, router as autoresearch_router

    # Load research config from global config file
    research_config = _load_research_config()

    # AutoResearch — the unified 6-step research framework.
    from llmwikify.apps.chat.db import AutoResearchDatabase
    autoresearch_db = AutoResearchDatabase(data_dir)
    # Get default wiki's tool registry for L3 chat routes
    # (Phase 4.5 / v0.36): injected so L3 doesn't import L4.
    try:
        default_tool_registry = registry.get_tool_registry(
            registry.get_default_wiki_id(),
        )
    except Exception:  # noqa: BLE001
        default_tool_registry = None
    set_autoresearch_deps(
        db=autoresearch_db,
        wiki_registry=registry,
        llm_client=agent_service._get_llm(),
        config=research_config,
        tool_registry=default_tool_registry,
    )
    logger.info("AutoResearch DB initialized at: %s", autoresearch_db.db_path)

    app.include_router(agent_router)
    app.include_router(autoresearch_router)

    _register_reproduction_routes(app, registry, agent_service)

    _mount_agent_spa(app)


def _register_reproduction_routes(
    app: FastAPI,
    registry: WikiRegistry,
    agent_service: Any,
) -> None:
    """Register paper/factor/strategy/reproduction routers and inject deps.

    Lives here (not in ``_register_wiki_routes``) because the reproduction
    routers need access to the LLM client and the reproduction session DB
    that the agent service owns. v0.4.0 — end-to-end reproduction pipeline.
    """
    from llmwikify.interfaces.server.http.paper import (
        router as paper_router,
        set_paper_deps,
    )
    from llmwikify.interfaces.server.http.factor import (
        router as factor_router,
        set_factor_deps,
    )
    from llmwikify.interfaces.server.http.strategy import (
        router as strategy_router,
        set_strategy_deps,
    )
    from llmwikify.interfaces.server.http.reproduction import (
        router as reproduction_router,
        set_repro_deps,
    )
    from llmwikify.reproduction.sessions import ReproductionDatabase

    data_dir = Path.home() / ".llmwikify" / "agent"
    data_dir.mkdir(parents=True, exist_ok=True)
    repro_db = ReproductionDatabase(data_dir / "reproduction.db")
    logger.info("Reproduction DB initialized at: %s", repro_db.db_path)

    raw_dir = Path(__file__).resolve().parents[5] / "raw"
    upload_dir = Path.home() / ".llmwikify" / "papers"
    logger.info("paper raw_dir: %s, upload_dir: %s", raw_dir, upload_dir)

    set_paper_deps(
        wiki_registry=registry,
        llm_client=agent_service._get_llm(),
        db=repro_db,
        raw_dir=raw_dir,
        upload_dir=upload_dir,
    )
    set_factor_deps(wiki_registry=registry)
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
