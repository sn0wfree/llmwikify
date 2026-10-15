"""搜索路由 — 跨 wiki 搜索（1 端点）。"""

from __future__ import annotations

from fastapi import APIRouter

from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def register_search_routes(app, registry: WikiRegistry) -> None:
    """注册跨 wiki 搜索路由。"""

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
