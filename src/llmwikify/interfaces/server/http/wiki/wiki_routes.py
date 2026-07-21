"""Wiki 路由 — 默认 wiki + Wiki-ID 路由（23 端点）。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from llmwikify.interfaces.server.http.wiki._common import (
    _serve_wiki_file,
    create_wiki_dependency,
)
from llmwikify.interfaces.server.http.wiki._wiki_ops import (
    enrich_status,
    get_wiki_guide,
    read_page_with_sink,
    wiki_or_404,
    write_page,
)
from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

logger = logging.getLogger(__name__)


def _get_wiki_db_and_id(registry: WikiRegistry, wiki_id: str | None = None):
    """获取 WikiDB 实例和 wiki_id（用于 token 操作）。

    Raises:
        HTTPException: 503 当 agent service 未初始化或 wiki_db 不可用
    """
    try:
        from llmwikify.interfaces.server.http.agent._common import get_agent_service
        service = get_agent_service()
        db = service.wiki_service._wiki_db
        resolved_id = wiki_id or service.wiki_service.get_default_wiki_id()
        return db, resolved_id
    except Exception as e:
        logger.exception("Failed to get wiki_db for write operation: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Wiki database unavailable — write operations require agent service",
        ) from None


def register_wiki_routes(app, registry: WikiRegistry) -> None:
    """注册默认 wiki + Wiki-ID 路由。"""
    get_wiki, get_wiki_by_id = create_wiki_dependency(registry)

    # ─── 默认 wiki 路由 ─────────────────────────────────────────

    wiki_router = APIRouter(prefix="/api/wiki", tags=["wiki"])

    @wiki_router.get("/status")
    async def wiki_status(wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Get wiki status summary."""
        return enrich_status(wiki.status())

    @wiki_router.get("/search")
    async def wiki_search(q: str, limit: int = 10, backend: str = "fts5", wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Full-text search across wiki pages."""
        return wiki.search(q, limit, backend=backend)

    @wiki_router.get("/page/{page_name:path}")
    async def wiki_read_page(page_name: str, wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Read a wiki page."""
        return read_page_with_sink(wiki, page_name)

    @wiki_router.post("/page")
    async def wiki_write_page(request: Request, wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Write a wiki page."""
        body = await request.json()
        confirm_token = request.query_params.get("confirm_token")
        db, wiki_id = _get_wiki_db_and_id(registry)
        return write_page(wiki, body.get("page_name", ""), body.get("content", ""), confirm_token, db, wiki_id)

    @wiki_router.get("/guide")
    async def wiki_guide(wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Get wiki guide: schema, overview, index, and API usage instructions."""
        return get_wiki_guide(wiki)

    @wiki_router.get("/sink/status")
    async def wiki_sink_status(wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Get sink buffer status."""
        return wiki.sink_status()

    @wiki_router.get("/lint")
    async def wiki_lint(
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        wiki: Wiki = Depends(get_wiki),  # noqa: B008
    ):
        """Health-check the wiki."""
        return wiki.lint(mode=mode, limit=limit, force=force)

    @wiki_router.get("/recommend")
    async def wiki_recommend(wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Get wiki recommendations."""
        return wiki.recommend()

    @wiki_router.get("/suggest_synthesis")
    async def wiki_suggest_synthesis(source_name: str | None = None, wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Get cross-source synthesis suggestions."""
        return wiki.suggest_synthesis(source_name=source_name)

    @wiki_router.get("/graph_analyze")
    async def wiki_graph_analyze(wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Analyze knowledge graph structure."""
        return wiki.graph_analyze()

    @wiki_router.get("/graph")
    async def wiki_graph(
        current_page: str | None = None,
        mode: str = "auto",
        wiki: Wiki = Depends(get_wiki),  # noqa: B008
    ):
        """Return graph data optimized for visualization."""
        from llmwikify.kernel.graph.visualizer import build_visualization_data
        return build_visualization_data(wiki.index, wiki, current_page, mode)

    @wiki_router.get("/file/{path:path}")
    async def wiki_serve_file(path: str, wiki: Wiki = Depends(get_wiki)):  # noqa -> Any: B008
        """Serve a raw file from the wiki root (PDF, markdown, source)."""
        return _serve_wiki_file(wiki.root, path)

    app.include_router(wiki_router)

    # ─── Wiki-ID 路由 ───────────────────────────────────────────

    wiki_id_router = APIRouter(prefix="/api/wiki", tags=["wiki"])

    @wiki_id_router.get("/{wiki_id}/status")
    async def wiki_status_by_id(wiki_id: str) -> Any:
        """Get wiki status by ID."""
        with wiki_or_404(registry, wiki_id):
            return enrich_status(registry.get_wiki_status(wiki_id))

    @wiki_id_router.get("/{wiki_id}/pages")
    async def wiki_pages_by_id(wiki_id: str) -> dict[str, Any]:
        """Get list of all pages in a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            page_names = wiki._get_existing_page_names()
            return {"pages": page_names, "count": len(page_names)}

    @wiki_id_router.get("/{wiki_id}/search")
    async def wiki_search_by_id(wiki_id: str, q: str, limit: int = 10, backend: str = "fts5") -> Any:
        """Search within a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return wiki.search(q, limit, backend=backend)

    @wiki_id_router.get("/{wiki_id}/page/{page_name:path}")
    async def wiki_read_page_by_id(wiki_id: str, page_name: str) -> Any:
        """Read a page from a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return read_page_with_sink(wiki, page_name)

    @wiki_id_router.post("/{wiki_id}/page")
    async def wiki_write_page_by_id(wiki_id: str, request: Request) -> Any:
        """Write a page to a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            body = await request.json()
            confirm_token = request.query_params.get("confirm_token")
            db, _ = _get_wiki_db_and_id(registry, wiki_id)
            return write_page(wiki, body.get("page_name", ""), body.get("content", ""), confirm_token, db, wiki_id)

    @wiki_id_router.get("/{wiki_id}/guide")
    async def wiki_guide_by_id(wiki_id: str) -> Any:
        """Get wiki guide: schema, overview, index, and API usage instructions."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return get_wiki_guide(wiki)

    @wiki_id_router.get("/{wiki_id}/lint")
    async def wiki_lint_by_id(
        wiki_id: str,
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
    ):
        """Health-check a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return wiki.lint(mode=mode, limit=limit, force=force)

    @wiki_id_router.get("/{wiki_id}/recommend")
    async def wiki_recommend_by_id(wiki_id: str) -> Any:
        """Get recommendations for a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return wiki.recommend()

    @wiki_id_router.get("/{wiki_id}/graph")
    async def wiki_graph_by_id(
        wiki_id: str,
        current_page: str | None = None,
        mode: str = "auto",
    ):
        """Get graph data for a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            from llmwikify.kernel.graph.visualizer import build_visualization_data
            return build_visualization_data(wiki.index, wiki, current_page, mode)

    @wiki_id_router.get("/{wiki_id}/sink/status")
    async def wiki_sink_status_by_id(wiki_id: str) -> Any:
        """Get sink buffer status for a specific wiki."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return wiki.sink_status()

    @wiki_id_router.get("/{wiki_id}/file/{path:path}")
    async def wiki_serve_file_by_id(wiki_id: str, path: str) -> Any:
        """Serve a raw file from the named wiki (PDF, markdown, source)."""
        with wiki_or_404(registry, wiki_id) as wiki:
            return _serve_wiki_file(wiki.root, path)

    app.include_router(wiki_id_router)
