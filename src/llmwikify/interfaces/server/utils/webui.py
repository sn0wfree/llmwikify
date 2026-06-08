"""WebUI static file utilities - single source of truth.

Used by both WikiServer core and legacy entry points.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


logger = logging.getLogger(__name__)


def find_webui_dist() -> Path | None:
    """Find the WebUI dist directory at the top-level ``ui/webui/dist``.

    Per the 4-layer refactor (Batch A2), frontend assets live at
    the top-level ``ui/`` directory. The old location
    ``src/llmwikify/web/webui/`` was removed.

    For dev mode, run ``cd ui/webui && npm run build`` first.

    Returns:
        Path to dist directory, or None if not found.
    """
    # webui.py is at: src/llmwikify/interfaces/server/utils/webui.py
    # Up 6 levels: utils → server → interfaces → llmwikify → src → repo root
    repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    candidate = repo_root / "ui" / "webui" / "dist"
    if candidate.exists() and (candidate / "index.html").exists():
        return candidate
    logger.warning("WebUI dist not found at %s; / will return 404", candidate)
    return None


def mount_webui(app: FastAPI) -> None:
    """Mount WebUI static files to a FastAPI app.

    Sets up SPA fallback routing for React/Vue/etc.

    Args:
        app: FastAPI application to mount WebUI onto
    """
    dist_dir = find_webui_dist()
    if not dist_dir:
        return

    logger.info(f"Mounting WebUI from {dist_dir}")

    # Mount static files with SPA support
    app.mount(
        "/",
        StaticFiles(directory=str(dist_dir), html=True),
        name="static",
    )
