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


class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """Middleware that returns index.html for 404s on non-API routes.

    This enables client-side routing (React Router) so paths like /agent,
    /edit, /dashboard all serve the SPA entry point.
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
        return FileResponse(str(self.index_html))


def mount_webui(app: FastAPI) -> None:
    """Mount WebUI static files to a FastAPI app.

    Sets up SPA fallback routing so client-side routes like /agent, /edit,
    /dashboard all return index.html.

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
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # SPA fallback middleware: intercepts 404s for non-API routes
    index_html = dist_dir / "index.html"
    app.add_middleware(SPAFallbackMiddleware, index_html=index_html, dist_dir=dist_dir)
