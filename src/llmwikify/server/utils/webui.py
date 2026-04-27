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
    """Find the WebUI dist directory.

    Supports multiple deployment modes:
    1. Installed mode: package/web/webui/dist/
    2. Dev mode: repo/src/llmwikify/web/webui/dist/
    3. Legacy: package/web/static/

    Returns:
        Path to dist directory, or None if not found
    """
    pkg_dir = Path(__file__).parent.parent.parent.parent
    candidates = [
        pkg_dir / "web" / "webui" / "dist",
        pkg_dir.parent.parent / "web" / "webui" / "dist",
        pkg_dir / "web" / "static",
    ]

    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate

    logger.warning("No WebUI dist found")
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
