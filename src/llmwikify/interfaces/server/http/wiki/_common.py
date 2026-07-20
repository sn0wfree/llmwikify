"""Wiki 路由共享 helper。

提供文件服务、Wiki 实例获取等共享功能。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.instance import WikiType
from llmwikify.kernel.multi_wiki.registry import WikiRegistry


def _serve_wiki_file(wiki_root: Path, path: str) -> FileResponse:
    """Resolve a wiki-relative file path safely and return a FileResponse.

    Rejects absolute paths and any resolved path that escapes ``wiki_root``.
    Handles URL-encoded paths (defense in depth against double encoding).
    """
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    path = unquote(path)
    root = wiki_root.resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"Path escapes wiki root: {path}") from None
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    media_type, _ = mimetypes.guess_type(str(target))
    # RFC 5987: filename*=UTF-8''<percent-encoded> for non-ASCII filenames
    ascii_name = target.name.encode('ascii', 'replace').decode('ascii')
    encoded_name = quote(target.name, safe='')
    content_disp = f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": content_disp},
    )


def create_wiki_dependency(registry: WikiRegistry) -> Any:
    """创建 FastAPI 依赖注入函数，用于获取默认 wiki。"""

    def _get_default_or_first_wiki_id() -> str:
        """Get default wiki_id or first registered wiki if only one exists."""
        default_id = registry.get_default_wiki_id()
        if default_id:
            return default_id
        wikis = registry.list_wikis()
        if len(wikis) == 1:
            return wikis[0].wiki_id
        elif len(wikis) == 0:
            raise HTTPException(status_code=400, detail="No wiki registered")
        raise HTTPException(status_code=400, detail="No default wiki configured")

    def get_wiki_by_id(wiki_id: str) -> Wiki:
        instance = registry.get_wiki_instance(wiki_id)
        if instance.wiki_type == WikiType.REMOTE:
            raise HTTPException(status_code=400, detail="Cannot access remote wiki directly")
        return registry.get_wiki(wiki_id)

    def get_wiki() -> Wiki:
        wiki_id = _get_default_or_first_wiki_id()
        return registry.get_wiki(wiki_id)

    return get_wiki, get_wiki_by_id
