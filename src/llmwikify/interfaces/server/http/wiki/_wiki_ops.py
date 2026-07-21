"""Wiki 核心业务处理器 —— 固定流程，不对外扩展。

包含 token-based 二次确认流程（POST /page）：
1. 写新 page → 直接成功（201）
2. 写已存在 page → 生成 confirmation_id (TTL=300s) → 409
3. 带 confirm_token 重试 → 校验 token + wiki_id + page_name + 过期 → 200

所有写操作依赖 agent service 提供的 WikiDatabase；服务不可用时返回 503。
"""

from __future__ import annotations

import fnmatch
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

logger = logging.getLogger(__name__)

CONFIRMATION_TTL_SECONDS = 300


# ─── Wiki 配置读取 ────────────────────────────────────────────

def load_wiki_config() -> dict:
    """从 ~/.llmwikify/llmwikify.json 读取 wiki 配置。

    Returns:
        wiki 配置字典，包含 allowed_remote_hosts 等字段。
        文件不存在或读取失败时返回默认值。
    """
    from llmwikify.foundation.config import Config

    return Config().get("wiki", {"allowed_remote_hosts": ["*"]})


def check_remote_wiki_config(allowed_hosts: list[str]) -> None:
    """启动时检查远程 wiki 配置，宽松默认值时发出提醒。"""
    if allowed_hosts == ["*"]:
        logger.warning(
            "Remote wiki registration allows all hosts "
            "(allowed_remote_hosts=['*']). "
            "Consider restricting to specific hosts for security. "
            "Example: allowed_remote_hosts=['*.company.com', '10.0.0.0/8']"
        )


# ─── Wiki 实例获取（上下文管理器）─────────────────────────────

@contextmanager
def wiki_or_404(registry: WikiRegistry, wiki_id: str) -> Iterator[Wiki]:
    """Get wiki by ID, raising HTTPException(404) if not found.

    Args:
        registry: WikiRegistry instance.
        wiki_id: Wiki ID to look up.

    Yields:
        Wiki instance.

    Raises:
        HTTPException: 404 if wiki not found.

    Usage::

        with wiki_or_404(registry, wiki_id) as wiki:
            return wiki.status()
    """
    try:
        yield registry.get_wiki(wiki_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Wiki not found: {wiki_id}"
        ) from None


# ─── Wiki 页面操作（固定流程）──────────────────────────────────

def read_page_with_sink(wiki: Wiki, page_name: str) -> dict:
    """读页面 + sink 合并。

    Args:
        wiki: Wiki 实例
        page_name: 页面名称

    Returns:
        页面数据 + sink 信息合并后的字典

    Raises:
        HTTPException: 页面不存在时返回 404
    """
    page_data = wiki.read_page(page_name)
    if isinstance(page_data, dict) and "error" in page_data:
        raise HTTPException(status_code=404, detail=page_data["error"])
    sink_info = wiki.query_sink.get_info_for_page(page_name)
    if isinstance(page_data, dict):
        return {**page_data, **sink_info}
    return page_data


def write_page(
    wiki: Wiki,
    page_name: str,
    content: str,
    confirm_token: str | None = None,
    db: object | None = None,
    wiki_id: str | None = None,
) -> dict:
    """写页面 + 校验 + token-based 二次确认。

    Args:
        wiki: Wiki 实例
        page_name: 页面名称
        content: 页面内容
        confirm_token: 可选的确认 token（从 409 响应获取）
        db: WikiDatabase 实例（用于 token 存储/验证/消费）
        wiki_id: Wiki ID（用于 token 绑定/校验）

    Returns:
        {"message": result, "page_name": page_name}

    Raises:
        HTTPException: 页面名为空返回 400；content 为空返回 400；
                       页面已存在且无 token 返回 409 + confirmation_id；
                       token 无效 / wiki_id 不匹配 / 过期 / page_name 不匹配 返回 400；
                       db 不可用 返回 503
    """
    if not page_name:
        raise HTTPException(status_code=400, detail="page_name required")
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="content required and must not be empty")

    existing = wiki.read_page(page_name)
    page_exists = "error" not in existing

    if page_exists:
        if confirm_token:
            if not db:
                raise HTTPException(
                    status_code=503,
                    detail="Wiki database unavailable — cannot verify confirmation token",
                )
            conf = db.get_confirmation_with_decoded_args(confirm_token)
            if not conf or conf.get("status") != "pending":
                raise HTTPException(
                    status_code=400, detail="Invalid or expired confirmation token"
                )
            if wiki_id and conf.get("wiki_id") != wiki_id:
                raise HTTPException(
                    status_code=400, detail="Token does not match wiki_id"
                )
            conf_args = conf.get("arguments", {})
            expires_at = conf_args.get("expires_at", 0)
            if expires_at and time.time() > expires_at:
                raise HTTPException(
                    status_code=400, detail="Confirmation token expired"
                )
            if conf_args.get("page_name") != page_name:
                raise HTTPException(
                    status_code=400, detail="Token does not match page_name"
                )
            db.delete_confirmation(confirm_token)
        else:
            if not db or not wiki_id:
                raise HTTPException(
                    status_code=503,
                    detail="Wiki database unavailable — cannot create confirmation token",
                )
            confirmation_id = uuid.uuid4().hex[:8]
            db.save_confirmation({
                "id": confirmation_id,
                "wiki_id": wiki_id,
                "tool": "wiki_page_update",
                "arguments": {
                    "page_name": page_name,
                    "expires_at": time.time() + CONFIRMATION_TTL_SECONDS,
                },
                "action_type": "write",
                "status": "pending",
            })
            content_preview = existing.get("content", "")[:500] if isinstance(existing, dict) else ""
            word_count = existing.get("word_count", 0) if isinstance(existing, dict) else 0
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "conflict",
                    "message": "Page already exists. Confirm update. Please judge whether to keep existing content or merge.",
                    "confirmation_id": confirmation_id,
                    "existing_page": {
                        "word_count": word_count,
                        "content_preview": content_preview,
                    },
                },
            )

    try:
        result = wiki.write_page(page_name, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"message": result, "page_name": page_name}


def enrich_status(status: dict) -> dict:
    """状态富化：pages_by_type → all_types。

    Args:
        status: wiki 状态字典

    Returns:
        添加 all_types 字段后的状态字典
    """
    if "pages_by_type" in status:
        status["all_types"] = list(status["pages_by_type"].keys())
    return status


def get_wiki_guide(wiki: Wiki) -> dict:
    """获取 wiki 使用指南：schema + 完整 API 说明 + 操作流程。

    Returns:
        dict with schema, api_guide, workflows, page_naming_rules,
        page_types, error_codes
    """
    schema_data = wiki.read_schema()
    schema_content = schema_data.get("content", "") if "error" not in schema_data else ""

    page_types = wiki._load_page_type_mapping()

    return {
        "schema": schema_content,
        "api_guide": {
            "bootstrap": {
                "GET /api/wiki/{wiki_id}/guide": "Start here — returns this guide (schema + API reference)",
            },
            "read": {
                "GET /api/wiki/{wiki_id}/page/{page_name}": {
                    "description": "Read a wiki page (supports .sink/ files)",
                    "example": "/api/wiki/mining_news/page/daily/2026-07-21",
                },
                "GET /api/wiki/{wiki_id}/page/overview": {
                    "description": "Read overview page (high-level wiki narrative)",
                },
                "GET /api/wiki/{wiki_id}/page/index": {
                    "description": "Read index page (full page catalog with summaries)",
                },
                "GET /api/wiki/{wiki_id}/pages": {
                    "description": "List all page names in the wiki",
                },
                "GET /api/wiki/{wiki_id}/search?q={query}": {
                    "description": "Full-text search across wiki pages",
                    "params": {"q": "search query", "limit": "max results (default 10)", "backend": "fts5 (default)"},
                    "example": "/api/wiki/mining_news/search?q=gold+mining&limit=10",
                },
            },
            "write": {
                "POST /api/wiki/{wiki_id}/page": {
                    "description": "Create a new page (returns 201) or confirm update of existing page (returns 409 with confirmation_id)",
                    "body": {
                        "page_name": "daily/2026-07-21 (NO .md suffix!)",
                        "content": "# Title\n\nFull markdown content...",
                        "confirm_token": "OPTIONAL — from 409 response, confirms update (one-shot, TTL 300s)",
                    },
                    "behavior": {
                        "new_page": "201 Created",
                        "existing_page_no_token": "409 Conflict + confirmation_id + existing_page preview",
                        "existing_page_with_valid_token": "200 Updated (token must match wiki_id + page_name + not expired)",
                        "content_missing": "400 Bad Request",
                        "token_invalid_or_expired_or_wiki_mismatch": "400 Bad Request",
                        "wiki_db_unavailable": "503 Service Unavailable",
                    },
                },
            },
            "health": {
                "GET /api/wiki/{wiki_id}/status": {
                    "description": "Wiki status summary (page count, graph stats, types)",
                },
                "GET /api/wiki/{wiki_id}/lint": {
                    "description": "Health check (broken links, orphans, contradictions)",
                    "params": {"mode": "check (default) or fix", "limit": "max issues (default 10)"},
                },
                "GET /api/wiki/{wiki_id}/sink/status": {
                    "description": "Pending sink buffer entries",
                },
                "GET /api/wiki/{wiki_id}/recommend": {
                    "description": "Missing page recommendations (frequently referenced but nonexistent)",
                },
            },
            "graph": {
                "GET /api/wiki/{wiki_id}/graph": {
                    "description": "Knowledge graph visualization data",
                    "params": {"current_page": "optional focus page", "mode": "auto (default)"},
                },
                "GET /api/wiki/{wiki_id}/graph_analyze": {
                    "description": "Graph analysis (community detection, export)",
                },
            },
            "files": {
                "GET /api/wiki/{wiki_id}/file/{path}": {
                    "description": "Serve raw file from wiki (PDF, markdown, source)",
                    "example": "/api/wiki/mining_news/file/raw/gold/article.md",
                },
            },
        },
        "workflows": {
            "agent_bootstrap": [
                "1. GET /api/wiki/{wiki_id}/guide — get this guide (schema, overview, index)",
                "2. Parse api_guide to learn all available endpoints",
                "3. Parse page_types to know directory structure (daily/, company/, industry/, etc.)",
                "4. Read index to understand current wiki state",
                "5. Search or read pages as needed for your task",
            ],
            "ingest_document": [
                "1. Place file in raw/ directory (or use CLI: python3 -m llmwikify ingest raw/file.pdf)",
                "2. GET /api/wiki/{wiki_id}/search?q='filename' — check if already ingested",
                "3. If not exists, POST /api/wiki/{wiki_id}/page with page_name='sources/slug' and content",
                "4. Optionally create/update related pages (company/, industry/, daily/)",
                "5. Verify: GET /api/wiki/{wiki_id}/page/{page_name}",
            ],
            "create_page": [
                "1. GET /api/wiki/{wiki_id}/search?q='topic' — check for duplicates",
                "2. If page exists, read first: GET /api/wiki/{wiki_id}/page/{page_name}",
                "3. POST /api/wiki/{wiki_id}/page with page_name (NO .md suffix) and full markdown content",
                "4. Use [[wikilinks]] to connect to related pages",
                "5. Verify: GET /api/wiki/{wiki_id}/page/{page_name}",
            ],
            "daily_summary": [
                "1. Search raw articles for target date: GET /api/wiki/{wiki_id}/search?q='YYYY-MM-DD'",
                "2. Read each article via GET /api/wiki/{wiki_id}/file/raw/{metal}/article.md",
                "3. Compose summary following wiki.md template (热点, 行业趋势, 公司动向, 地理分布, 市场观点)",
                "4. POST /api/wiki/{wiki_id}/page with page_name='daily/YYYY-MM-DD'",
                "5. Update related industry/company pages if significant new information",
            ],
            "health_check": [
                "1. GET /api/wiki/{wiki_id}/lint — check for broken links, orphans, issues",
                "2. GET /api/wiki/{wiki_id}/recommend — find missing pages that are frequently referenced",
                "3. Fix issues by creating missing pages or updating broken links",
                "4. Re-run GET /api/wiki/{wiki_id}/lint to verify fixes",
            ],
            "search_and_read": [
                "1. GET /api/wiki/{wiki_id}/search?q='query'&limit=10 — find relevant pages",
                "2. Review search results (page_name, score, snippet)",
                "3. GET /api/wiki/{wiki_id}/page/{page_name} — read full content of relevant pages",
                "4. If page has has_sink=true, also read sink: GET /api/wiki/{wiki_id}/page/sink/{page_name}",
            ],
        },
        "page_naming_rules": {
            "no_md_suffix": "page_name must NOT end with .md (auto-appended by server)",
            "no_wiki_prefix": "page_name must NOT start with wiki/ (added automatically)",
            "no_traversal": "page_name must NOT contain .. (path traversal blocked)",
            "path_format": "Use 'directory/name' format for organized pages",
            "examples": {
                "daily": "daily/2026-07-21",
                "weekly": "weekly/2026-W29",
                "monthly": "monthly/2026-07",
                "company": "company/Kinross Gold",
                "industry": "industry/Gold Industry",
                "source": "sources/ontario-fast-tracks-kinross-great-bear",
                "entity": "entities/Great Bear Project",
                "concept": "concepts/Mining Supercycle",
            },
        },
        "page_types": page_types,
        "error_codes": {
            "400": "Bad request — invalid page_name, missing content, invalid/expired/mismatched confirmation token",
            "404": "Not found — wiki_id or page_name doesn't exist",
            "409": "Conflict — page exists; retry with ?confirm_token=<confirmation_id> to confirm update (TTL: 300s)",
            "500": "Internal server error — contact admin",
            "503": "Service unavailable — agent service / wiki DB not initialized",
        },
    }


# ─── 远程 Wiki URL 校验（SSRF 防护）────────────────────────────

def validate_remote_url(url: str, allowed_hosts: list[str]) -> None:
    """校验远程 wiki URL 是否在白名单中。

    Args:
        url: 远程 wiki URL
        allowed_hosts: 允许的主机名模式列表（支持通配符）

    Raises:
        HTTPException: URL 无效或不在白名单中返回 400
    """
    if not allowed_hosts:
        raise HTTPException(
            status_code=400, detail="Remote wiki registration is disabled"
        )
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400, detail="URL must use http or https scheme"
        )
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="URL must have a hostname")
    for pattern in allowed_hosts:
        if fnmatch.fnmatch(hostname, pattern):
            return  # 匹配，允许
    raise HTTPException(
        status_code=400,
        detail=f"Host {hostname} not in allowed_remote_hosts",
    )
