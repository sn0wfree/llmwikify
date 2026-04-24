"""Unified server core for llmwikify.

Combines MCP protocol, REST API, and WebUI into a single FastAPI application.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from llmwikify.core import Wiki

from ..mcp.adapter import MCPAdapter
from .http.middleware import AuthMiddleware
from .http.routes import register_routes


logger = logging.getLogger(__name__)


class WikiServer:
    """llmwikify Unified Server - combines all service layers.

    Features:
    - MCP protocol adapter for AI agent integration
    - REST API with FastAPI (auto docs at /docs)
    - WebUI static file serving (React SPA)
    - Optional API key authentication
    - Optional Agent features

    Usage:
        # HTTP mode (full features)
        server = WikiServer(wiki, agent=agent, enable_webui=True)
        server.run(host="127.0.0.1", port=8765)

        # Pure MCP mode (stdio)
        server = WikiServer(wiki, enable_rest=False, enable_webui=False)
        await server.run_mcp_stdio()
    """

    def __init__(
        self,
        wiki: Wiki,
        agent: Any | None = None,
        api_key: str | None = None,
        mcp_name: str | None = None,
        enable_mcp: bool = True,
        enable_rest: bool = True,
        enable_webui: bool = True,
        cors_enabled: bool = True,
    ):
        self.wiki = wiki
        self.agent = agent
        self.api_key = api_key
        self.enable_mcp = enable_mcp
        self.enable_rest = enable_rest
        self.enable_webui = enable_webui

        # 1. Build MCP adapter
        if enable_mcp:
            self.mcp = MCPAdapter(wiki, name=mcp_name)

        # 2. Build FastAPI application
        self.app = self._build_app(cors_enabled=cors_enabled)

        # 3. Register REST API routes
        if enable_rest:
            register_routes(self.app, wiki, agent)

        # 4. Mount WebUI static files
        if enable_webui:
            self._mount_webui()

    def _build_app(self, cors_enabled: bool = True) -> FastAPI:
        """Build and configure FastAPI application."""
        app = FastAPI(
            title="llmwikify",
            version="0.30.0",
            description="LLM Wiki Knowledge Base API",
            docs_url="/docs",
            redoc_url="/redoc",
        )

        # CORS support
        if cors_enabled:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # Auth middleware
        if self.api_key:
            app.add_middleware(AuthMiddleware, api_key=self.api_key)

        # Mount MCP endpoint
        if self.enable_mcp and hasattr(self, "mcp"):
            app.mount("/mcp", self.mcp.asgi_app)

        # Health check endpoint
        @app.get("/api/health", tags=["system"])
        async def health_check():
            """Get server health status."""
            page_count = len(list(self.wiki.wiki_dir.glob("**/*.md"))) if self.wiki.wiki_dir.exists() else 0
            return {
                "status": "ok",
                "version": "0.30.0",
                "wiki": {
                    "initialized": self.wiki.initialized,
                    "root": str(self.wiki.root),
                    "page_count": page_count,
                },
                "features": {
                    "mcp": self.enable_mcp,
                    "agent": self.agent is not None,
                    "webui": self.enable_webui,
                    "auth": self.api_key is not None,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Lifecycle hooks
        @app.on_event("shutdown")
        async def shutdown_event():
            logger.info("llmwikify server shutting down")
            self.wiki.close()
            if self.agent:
                if hasattr(self.agent, "shutdown"):
                    await self.agent.shutdown()

        return app

    def _mount_webui(self) -> None:
        """Mount React SPA static files with multi-path fallback."""
        dist_dir = self._find_webui_dist()
        if not dist_dir:
            logger.warning("No WebUI dist found, serving without static files")
            return

        logger.info(f"Mounting WebUI from {dist_dir}")
        self.app.mount(
            "/",
            StaticFiles(directory=str(dist_dir), html=True),
            name="static",
        )

    def _find_webui_dist(self) -> Path | None:
        """Find WebUI dist directory (supports multiple deployment modes)."""
        pkg_dir = Path(__file__).parent.parent
        candidates = [
            # 1. Installed mode: <package>/web/webui/dist/
            pkg_dir / "web" / "webui" / "dist",
            # 2. Dev mode: <repo>/src/llmwikify/web/webui/dist/
            pkg_dir.parent.parent / "web" / "webui" / "dist",
            # 3. Legacy mode: <package>/web/static/
            pkg_dir / "web" / "static",
        ]
        for candidate in candidates:
            if candidate.exists() and (candidate / "index.html").exists():
                return candidate
        return None

    def run(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run unified HTTP server."""
        import uvicorn
        uvicorn.run(self.app, host=host, port=port, log_level="info")

    async def run_mcp_stdio(self) -> None:
        """Run MCP server in stdio mode (pure MCP, no HTTP)."""
        if hasattr(self, "mcp"):
            await self.mcp.run_stdio()

    async def run_mcp_http(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run standalone MCP HTTP server (without WebUI/REST)."""
        if hasattr(self, "mcp"):
            await self.mcp.run_http(host, port)
