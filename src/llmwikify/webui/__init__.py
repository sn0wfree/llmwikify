"""The packaged WebUI bundle.

The Vite build writes here (``ui/webui/vite.config.ts`` → ``outDir``),
so ``pip install llmwikify`` ships a working ``serve --web`` UI instead
of a 404.

The directory is empty in a source checkout until ``npm run build`` has
run; :func:`llmwikify.interfaces.server.utils.webui.find_webui_dist`
reports that case instead of raising.
"""

from __future__ import annotations

from pathlib import Path

#: Where the built bundle lives inside the package.
DIST_DIR = Path(__file__).parent / "dist"


def dist_exists() -> bool:
    """True when the WebUI bundle is present in the package."""
    return (DIST_DIR / "index.html").exists()


__all__ = ["DIST_DIR", "dist_exists"]
