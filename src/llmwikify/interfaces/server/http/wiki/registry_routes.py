"""Wikis 注册路由 — Wiki 注册管理（8 端点）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from llmwikify.interfaces.server.http.wiki._wiki_ops import (
    check_remote_wiki_config,
    load_wiki_config,
    validate_remote_url,
    wiki_or_404,
)
from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def register_registry_routes(app, registry: WikiRegistry) -> None:
    """注册 Wikis 注册路由。"""

    # 加载远程 wiki 白名单配置
    wiki_config = load_wiki_config()
    allowed_remote_hosts = wiki_config.get("allowed_remote_hosts", ["*"])
    check_remote_wiki_config(allowed_remote_hosts)

    wikis_router = APIRouter(prefix="/api/wikis", tags=["wikis"])

    @wikis_router.get("")
    async def list_wikis() -> dict[str, Any]:
        """List all registered wikis."""
        wikis = registry.list_wikis()
        return {
            "wikis": [w.to_dict() for w in wikis],
            "default_wiki_id": registry.get_default_wiki_id(),
        }

    @wikis_router.post("")
    async def register_wiki(request: Request) -> Any:
        """Register a new wiki."""
        body = await request.json()
        wiki_id = body.get("wiki_id")
        name = body.get("name", wiki_id)
        wiki_type = body.get("type", "local")

        if not wiki_id:
            raise HTTPException(status_code=400, detail="wiki_id required")

        if wiki_type == "remote":
            url = body.get("url")
            if not url:
                raise HTTPException(status_code=400, detail="url required for remote wiki")
            validate_remote_url(url, allowed_remote_hosts)  # SSRF 校验
            instance = registry.register_remote(
                wiki_id=wiki_id,
                name=name,
                url=url,
                api_key=body.get("api_key"),
                timeout=body.get("timeout", 30),
                verify_ssl=body.get("verify_ssl", True),
            )
        else:
            root = body.get("root")
            if not root:
                raise HTTPException(status_code=400, detail="root required for local wiki")
            instance = registry.register_wiki(
                wiki_id=wiki_id,
                name=name,
                root=Path(root),
            )

        return instance.to_dict()

    @wikis_router.get("/{wiki_id}")
    async def get_wiki_info(wiki_id: str) -> Any:
        """Get wiki details."""
        with wiki_or_404(registry, wiki_id):
            instance = registry.get_wiki_instance(wiki_id)
            return instance.to_dict()

    @wikis_router.put("/{wiki_id}")
    async def update_wiki(wiki_id: str, request: Request) -> Any:
        """Update wiki configuration."""
        body = await request.json()
        with wiki_or_404(registry, wiki_id):
            instance = registry.get_wiki_instance(wiki_id)
            # Update allowed fields
            if "name" in body:
                instance.name = body["name"]
            if "is_default" in body and body["is_default"]:
                registry.set_default_wiki(wiki_id)
            return instance.to_dict()

    @wikis_router.delete("/{wiki_id}")
    async def unregister_wiki(wiki_id: str) -> dict[str, Any]:
        """Unregister a wiki."""
        with wiki_or_404(registry, wiki_id):
            registry.unregister_wiki(wiki_id)
            return {"message": f"Wiki {wiki_id} unregistered"}

    @wikis_router.post("/{wiki_id}/reload")
    async def reload_wiki(wiki_id: str) -> Any:
        """Reload/re-index a wiki."""
        with wiki_or_404(registry, wiki_id):
            result = registry.reload_wiki(wiki_id)
            if result.get("status") == "error":
                raise HTTPException(status_code=500, detail=result.get("message"))
            return result

    @wikis_router.get("/{wiki_id}/health")
    async def wiki_health(wiki_id: str) -> Any:
        """Check wiki health."""
        with wiki_or_404(registry, wiki_id):
            status = registry.get_wiki_status(wiki_id)
            return status

    @wikis_router.post("/scan")
    async def scan_wikis(request: Request) -> dict[str, Any]:
        """Trigger directory scan for wikis.

        Only paths under the user's home directory are accepted to
        prevent filesystem enumeration attacks.
        """
        body = await request.json()
        raw_paths = body.get("scan_paths", ["."])
        scan_depth = body.get("scan_depth", 2)

        # Path traversal guard: only allow paths under $HOME
        home = Path.home().resolve()
        scan_paths: list[str] = []
        for p in raw_paths:
            resolved = Path(p).resolve()
            if not (resolved == home or str(resolved).startswith(str(home) + "/")):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path outside home directory: {p}",
                )
            scan_paths.append(str(resolved))

        new_wikis = registry.scan_directories(scan_paths, scan_depth)
        return {
            "new_wikis": [w.to_dict() for w in new_wikis],
            "count": len(new_wikis),
        }

    app.include_router(wikis_router)
