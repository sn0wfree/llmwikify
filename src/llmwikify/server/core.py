"""Unified server core for llmwikify.

Combines MCP protocol, REST API, and WebUI into a single FastAPI application.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Union

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llmwikify.core import Wiki
from llmwikify.core.wiki_registry import WikiRegistry
from llmwikify.server.constants import DEFAULT_HOST, DEFAULT_PORT

from ..mcp.adapter import MCPAdapter
from .http.middleware import AuthMiddleware
from .http.routes import register_routes
from .utils.webui import mount_webui


logger = logging.getLogger(__name__)


class WikiServer:
    """llmwikify Unified Server - combines all service layers.

    Features:
    - MCP protocol adapter for AI agent integration
    - REST API with FastAPI (auto docs at /docs)
    - WebUI static file serving (React SPA)
    - Optional API key authentication
    - Multi-wiki support via WikiRegistry

    Usage:
        # Single wiki mode (backward compatible)
        server = WikiServer(wiki, enable_webui=True)
        server.run(host="127.0.0.1", port=8765)

        # Multi-wiki mode
        registry = WikiRegistry(config)
        registry.initialize()
        server = WikiServer(registry, enable_webui=True)
        server.run(host="127.0.0.1", port=8765)

        # Pure MCP mode (stdio)
        server = WikiServer(wiki, enable_rest=False, enable_webui=False)
        await server.run_mcp_stdio()
    """

    def __init__(
        self,
        wiki: Wiki | WikiRegistry,
        api_key: str | None = None,
        mcp_name: str | None = None,
        enable_mcp: bool = True,
        enable_rest: bool = True,
        enable_webui: bool = True,
        cors_enabled: bool = True,
    ):
        # Support both single Wiki and WikiRegistry
        if isinstance(wiki, WikiRegistry):
            self.registry = wiki
            self.wiki = wiki.get_default_wiki() if wiki.get_default_wiki_id() else None
        else:
            # Single wiki mode: create a registry with one wiki
            self.wiki = wiki
            self.registry = None  # Will be created if needed

        self.api_key = api_key
        self.enable_mcp = enable_mcp
        self.enable_rest = enable_rest
        self.enable_webui = enable_webui
        self.mcp: MCPAdapter | None = None

        # 1. Build MCP adapter
        if enable_mcp:
            if self.registry:
                # Multi-wiki mode: use default wiki for MCP
                self.mcp = MCPAdapter(self.wiki, name=mcp_name)
            else:
                self.mcp = MCPAdapter(wiki, name=mcp_name)

        # 2. Build FastAPI application
        self.app = self._build_app(cors_enabled=cors_enabled)

        # 3. Register REST API routes
        if enable_rest:
            register_routes(self.app, wiki, self.registry)

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
        if self.mcp is not None:
            app.mount("/mcp", self.mcp.asgi_app)

        # Health check endpoint
        @app.get("/api/health", tags=["system"])
        async def health_check():
            """Get server health status."""
            if self.registry:
                # Multi-wiki mode
                wikis = self.registry.list_wikis()
                return {
                    "status": "ok",
                    "version": "0.31.0",
                    "mode": "multi-wiki",
                    "wiki_count": len(wikis),
                    "default_wiki_id": self.registry.get_default_wiki_id(),
                    "features": {
                        "mcp": self.enable_mcp,
                        "webui": self.enable_webui,
                        "auth": self.api_key is not None,
                        "multi_wiki": True,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }
            else:
                # Single wiki mode
                page_count = len(list(self.wiki.wiki_dir.glob("**/*.md"))) if self.wiki.wiki_dir.exists() else 0
                return {
                    "status": "ok",
                    "version": "0.31.0",
                    "mode": "single-wiki",
                    "wiki": {
                        "initialized": self.wiki.is_initialized(),
                        "root": str(self.wiki.root),
                        "page_count": page_count,
                    },
                    "features": {
                        "mcp": self.enable_mcp,
                        "webui": self.enable_webui,
                        "auth": self.api_key is not None,
                        "multi_wiki": False,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }

        # Lifecycle hooks
        @app.on_event("shutdown")
        async def shutdown_event():
            logger.info("llmwikify server shutting down")
            if self.registry:
                self.registry.close()
            elif self.wiki:
                self.wiki.close()

        return app

    def _mount_webui(self) -> None:
        """Mount React SPA static files (single source of truth)."""
        mount_webui(self.app)

    def run(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        """Run unified HTTP server."""
        import uvicorn
        uvicorn.run(self.app, host=host, port=port, log_level="info")

    async def run_mcp_stdio(self) -> None:
        """Run MCP server in stdio mode (pure MCP, no HTTP)."""
        if self.mcp is not None:
            await self.mcp.run_stdio()

    async def run_mcp_http(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run standalone MCP HTTP server (without WebUI/REST)."""
        if self.mcp is not None:
            await self.mcp.run_http(host, port)
