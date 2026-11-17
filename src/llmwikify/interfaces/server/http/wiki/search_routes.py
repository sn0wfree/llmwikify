"""搜索路由 — 跨 wiki 搜索（1 端点）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def _filter_by_claim(
    request: Request, requested: list[str] | None, known_wikis: list[str]
) -> list[str] | None:
    """Restrict a wiki-id list to what the caller can actually read.

    P0-1: ``GET /api/search/cross`` used to accept an arbitrary
    ``wikis`` filter (or none = search everything), so a token scoped
    to one wiki could read another.

    P4b: visibility = snapshot ∩ live (``accessible_wikis``) — the same
    set a point-read would be allowed on, so the list never includes a
    wiki that would 403 on open.

    Returns ``None`` when the caller may see everything (local_mode —
    no claims attached), otherwise the intersected list.
    """
    claims = getattr(request.state, "auth_claims", None)
    if claims is None:
        return requested  # local_mode: middleware bypassed, trust
    from llmwikify.foundation.auth import accessible_wikis

    allowed = accessible_wikis(claims, known_wikis)
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
        known = [w.wiki_id for w in registry.list_wikis()]
        wiki_ids = _filter_by_claim(request, requested, known)
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
        results = registry.cross_wiki_search(q, wiki_ids, limit, backend=backend)
        return {
            "results": results,
            "total_results": len(results),
            "searched_wikis": wiki_ids or [w.wiki_id for w in registry.list_wikis()],
        }

    app.include_router(search_router)
