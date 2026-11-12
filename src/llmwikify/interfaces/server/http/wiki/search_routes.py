"""搜索路由 — 跨 wiki 搜索（1 端点）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def _filter_by_claim(request: Request, requested: list[str] | None) -> list[str] | None:
    """Restrict a wiki-id list to the caller's ``wikis`` claim.

    P0-1: ``GET /api/search/cross`` and friends used to accept an
    arbitrary ``wikis`` filter (or none = search everything), so a token
    scoped to one wiki could read another. The claim is now enforced
    here instead of only by URL prefix in the middleware.

    Returns ``None`` when the caller may see everything (no claims, or
    ``wikis=["*"]``), otherwise the intersected list — possibly empty,
    in which case the route must 403 rather than silently return nothing.
    """
    claims = getattr(request.state, "auth_claims", None)
    if claims is None or "*" in claims.wikis:
        return requested
    allowed = set(claims.wikis)
    if requested is None:
        return sorted(allowed)
    return [w for w in requested if w in allowed]


def register_search_routes(app, registry: WikiRegistry) -> None:
    """注册跨 wiki 搜索路由。"""

    search_router = APIRouter(prefix="/api/search", tags=["search"])

    @search_router.get("/cross")
    async def cross_wiki_search(
        request: Request,
        q: str,
        limit: int = 10,
        wikis: str | None = None,
        backend: str = "fts5",
    ):
        """Search across multiple wikis.

        Args:
            q: Search query
            limit: Results per wiki
            wikis: Comma-separated wiki IDs (empty = all, subject to the
                caller's ``wikis`` claim)
            backend: Search backend
        """
        requested = wikis.split(",") if wikis else None
        wiki_ids = _filter_by_claim(request, requested)
        if wiki_ids is not None and not wiki_ids:
            claims = getattr(request.state, "auth_claims", None)
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "forbidden_wiki",
                    "detail": (
                        f"Token does not cover any requested wiki. "
                        f"Allowed: {list(getattr(claims, 'wikis', []))!r}."
                    ),
                },
            )
        results = registry.cross_wiki_search(q, wiki_ids, limit)
        return {
            "results": results,
            "total_results": len(results),
            "searched_wikis": wiki_ids or [w.wiki_id for w in registry.list_wikis()],
        }

    app.include_router(search_router)
