"""Unified server core for llmwikify.

Combines MCP protocol, REST API, and WebUI into a single FastAPI application.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry
from llmwikify.interfaces.server.constants import DEFAULT_HOST, DEFAULT_PORT

from ..mcp.adapter import MCPAdapter
from .http.middleware import AuthMiddleware
from .http.routes import register_routes
from .utils.webui import mount_webui

logger = logging.getLogger(__name__)

def setup_logging(log_dir: Path | None = None) -> None:
    """Configure root logger with file + stream handlers."""
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if log_dir is None:
        log_dir = Path.home() / ".llmwikify" / "agent"
    log_dir.mkdir(parents=True, exist_ok=True)

    fh = RotatingFileHandler(log_dir / "server.log", maxBytes=10 * 1024 * 1024, backupCount=5)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

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
        # Unified architecture: always use WikiRegistry
        if isinstance(wiki, WikiRegistry):
            self.registry = wiki
        else:
            # Single wiki mode: create a registry and auto-register the wiki
            from llmwikify.kernel.multi_wiki.instance import WikiType
            self.registry = WikiRegistry(config={})
            wiki_id = str(wiki.root).split('/')[-1] or 'default'
            self.registry.register_wiki(
                wiki_id=wiki_id,
                name=wiki_id.replace('-', ' ').replace('_', ' ').title(),
                root=wiki.root,
                wiki_type=WikiType.LOCAL,
                is_default=True,
            )
        # Get default wiki - if none set but only one wiki exists, use that
        default_id = self.registry.get_default_wiki_id()
        if not default_id:
            wikis = self.registry.list_wikis()
            if len(wikis) == 1:
                default_id = wikis[0].wiki_id
                self.registry.set_default_wiki(default_id)
        if isinstance(wiki, Wiki):
            self.wiki = wiki
        else:
            self.wiki = self.registry.get_default_wiki()

        self.api_key = api_key
        self.enable_mcp = enable_mcp
        self.enable_rest = enable_rest
        self.enable_webui = enable_webui
        self.mcp: MCPAdapter | None = None

        # 1. Build MCP adapter
        if enable_mcp:
            self.mcp = MCPAdapter(self.wiki, name=mcp_name)

        # 2. Build FastAPI application
        self.app = self._build_app(cors_enabled=cors_enabled)

        # 3. Register REST API routes
        if enable_rest:
            register_routes(self.app, self.registry)

        # 4. Mount WebUI static files
        if enable_webui:
            self._mount_webui()

    def _build_app(self, cors_enabled: bool = True) -> FastAPI:
        """Build and configure FastAPI application."""
        app = FastAPI(
            title="llmwikify",
            version="0.31.0",
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

        # Phase 4.3 (v0.36): Rate limit middleware. Token-bucket
        # per IP, applied to /api/agent/* routes only. Default
        # 60 req/min; set RATE_LIMIT_PER_MIN=0 to disable.
        from llmwikify.interfaces.server.http.middleware import (
            RateLimitMiddleware,
        )
        app.add_middleware(RateLimitMiddleware)

        # Request logging middleware - logs every request for debugging
        @app.middleware("http")
        async def log_requests(request: Request, call_next):
            response = await call_next(request)
            if response.status_code >= 400:
                client = request.client.host if request.client else "?"
                logger.info(f"[req] {request.method} {request.url.path} → {response.status_code} | client={client}")
            return response

        # Mount MCP endpoint
        if self.mcp is not None:
            app.mount("/mcp", self.mcp.asgi_app)

        # Health check endpoint
        @app.get("/api/health", tags=["system"])
        async def health_check():
            """Get server health status."""
            wikis = self.registry.list_wikis()
            wiki_count = len(wikis)

            # Determine mode: multi-wiki only if multiple wikis actually exist
            # (even with is_default set, single wiki = single-wiki mode)
            is_multi = wiki_count > 1

            if is_multi:
                return {
                    "status": "ok",
                    "version": "0.31.0",
                    "mode": "multi-wiki",
                    "wiki_count": wiki_count,
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
                # Single wiki mode (1 wiki, no explicit default)
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
        setup_logging()
        import uvicorn
        logger.info(f"llmwikify server starting on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port, log_level="info")

    async def run_mcp_stdio(self) -> None:
        """Run MCP server in stdio mode (pure MCP, no HTTP)."""
        if self.mcp is not None:
            await self.mcp.run_stdio()

    async def run_mcp_http(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run standalone MCP HTTP server (without WebUI/REST)."""
        if self.mcp is not None:
            await self.mcp.run_http(host, port)
