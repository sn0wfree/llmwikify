"""Wiki 核心业务处理器 —— 固定流程，不对外扩展。

Wiki 操作是稳定的核心功能，不需要可组合的 Handler 框架。
使用简单的函数式 API，清晰易懂。
"""

from __future__ import annotations

import fnmatch
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

logger = logging.getLogger(__name__)


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


def write_page(wiki: Wiki, page_name: str, content: str) -> dict:
    """写页面 + 校验。

    Args:
        wiki: Wiki 实例
        page_name: 页面名称
        content: 页面内容

    Returns:
        {"message": result, "page_name": page_name}

    Raises:
        HTTPException: 页面名为空返回 400，无效页面名返回 400
    """
    if not page_name:
        raise HTTPException(status_code=400, detail="page_name required")
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
    """获取 wiki 使用指南：schema、overview、index + API 说明。

    Returns:
        dict with schema, overview, index, api_guide, page_types
    """
    schema_data = wiki.read_schema()
    schema_content = schema_data.get("content", "") if "error" not in schema_data else ""

    overview_data = wiki.read_page("overview")
    overview_content = overview_data.get("content") if "error" not in overview_data else None

    index_content = wiki._get_index_content()

    page_types = wiki._load_page_type_mapping()

    return {
        "schema": schema_content,
        "overview": overview_content,
        "index": index_content,
        "api_guide": {
            "write_page": {
                "endpoint": "POST /api/wiki/{wiki_id}/page",
                "body": {
                    "page_name": "daily/2026-07-21 (NO .md suffix!)",
                    "content": "# Title\n\nContent...",
                    "query": "optional query for wikify",
                },
                "rules": [
                    "page_name must NOT end with .md",
                    "page_name must NOT start with wiki/",
                    "page_name must NOT contain ..",
                    "Both content and query are recommended",
                ],
            },
            "read_page": {
                "endpoint": "GET /api/wiki/{wiki_id}/page/{page_name}",
                "example": "/api/wiki/mining_news/page/daily/2026-07-21",
            },
            "search": {
                "endpoint": "GET /api/wiki/{wiki_id}/search?q={query}",
                "example": "/api/wiki/mining_news/search?q=gold+mining",
            },
            "guide": {
                "endpoint": "GET /api/wiki/{wiki_id}/guide",
                "description": "This endpoint — returns all wiki context for agents",
            },
        },
        "page_types": page_types,
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
