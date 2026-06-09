"""WebUI static file utilities - single source of truth.

Used by both WikiServer core and legacy entry points.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, Response


logger = logging.getLogger(__name__)

# index.html must always revalidate so users get the latest chunk refs
# after a new build (Vite hashes chunks, but stale index.html → stale chunks)
INDEX_HTML_CACHE_CONTROL = "no-cache, must-revalidate"

# Hashed assets under /assets/* are content-addressed and safe to cache forever
HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


def find_webui_dist() -> Path | None:
    """Find the WebUI dist directory at the top-level ``ui/webui/dist``.

    Returns:
        Path to dist directory, or None if not found.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    candidate = repo_root / "ui" / "webui" / "dist"
    if candidate.exists() and (candidate / "index.html").exists():
        return candidate
    logger.warning("WebUI dist not found at %s; / will return 404", candidate)
    return None


class _CacheControlledStaticFiles(StaticFiles):
    """StaticFiles subclass that sets long-lived cache headers for hashed assets.

    Vite/Rollup emits filenames like ``Editor-BKfmafmn.js`` whose hash
    changes whenever the content changes. A ``max-age=1y, immutable``
    header is safe because a new build produces a new hash, forcing the
    browser (and any CDN in front) to fetch the updated file by name.
    """

    async def get_response(self, path, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = HASHED_ASSET_CACHE_CONTROL
        return response


class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """Middleware that returns index.html for 404s on non-API routes.

    This enables client-side routing (React Router) so paths like /agent,
    /edit, /dashboard all serve the SPA entry point.

    index.html is served with ``Cache-Control: no-cache, must-revalidate``
    so browsers and proxies always revalidate it. A new build replaces
    index.html in place; if the cached copy is stale it would still
    reference now-deleted chunk hashes (e.g. ``Editor-rXkTDZD7.js``),
    causing the dynamic-import failures users saw.
    """

    def __init__(self, app, index_html: Path, dist_dir: Path):
        super().__init__(app)
        self.index_html = index_html
        self.dist_dir = dist_dir

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only intercept 404s
        if response.status_code != 404:
            return response

        path = request.url.path

        # Skip API routes — let them 404 properly
        if path.startswith("/api/"):
            return response
        # Skip FastAPI internal routes
        if path in ("/docs", "/redoc", "/openapi.json", "/openapi.yaml"):
            return response
        # Skip actual static files (JS, CSS, images in dist/)
        rel = path.lstrip("/")
        if (self.dist_dir / rel).is_file():
            return response
        # Skip favicon / common static assets
        if any(path.endswith(ext) for ext in (".ico", ".png", ".svg", ".jpg", ".gif", ".woff", ".woff2")):
            return response

        # SPA fallback: serve index.html for client-side routes
        response = FileResponse(str(self.index_html))
        response.headers["Cache-Control"] = INDEX_HTML_CACHE_CONTROL
        return response


def mount_webui(app: FastAPI) -> None:
    """Mount WebUI static files to a FastAPI app.

    Sets up SPA fallback routing so client-side routes like /agent, /edit,
    /dashboard all return index.html. Cache policy:

      - ``/assets/*`` (hashed chunks) — long-lived, immutable
      - ``index.html`` (entry point)  — ``no-cache, must-revalidate``
        so a new build is picked up immediately and the browser never
        references a chunk that was deleted by the latest build.

    Args:
        app: FastAPI application to mount WebUI onto
    """
    dist_dir = find_webui_dist()
    if not dist_dir:
        return

    logger.info(f"Mounting WebUI from {dist_dir}")

    # Mount static files (css/js/images) — NOT at / to avoid swallowing all routes
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets",
            _CacheControlledStaticFiles(directory=str(assets_dir)),
            name="assets",
        )

    # SPA fallback middleware: intercepts 404s for non-API routes
    index_html = dist_dir / "index.html"
    app.add_middleware(SPAFallbackMiddleware, index_html=index_html, dist_dir=dist_dir)
