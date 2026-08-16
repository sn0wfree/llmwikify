"""Jina Reader URL extractor — converts URLs to clean markdown.

Uses Jina Reader API (r.jina.ai) for:
- JS-rendered SPAs (headless Chrome)
- PDFs, Office docs, images (VLM captioning)
- Clean markdown extraction

Falls back to None on failure (caller should try trafilatura).
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import ExtractedContent

logger = logging.getLogger(__name__)


def extract_via_jina(url: str, api_key: str | None = None) -> ExtractedContent | None:
    """Extract content from a URL via Jina Reader (r.jina.ai).

    Args:
        url: The URL to extract content from.
        api_key: Optional Jina API key for higher limits.

    Returns:
        ExtractedContent on success, None on failure.
    """
    try:
        import httpx

        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-Return-Format": "json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        content_data = data.get("data", data)
        content = content_data.get("content", "")
        title = content_data.get("title", "")

        if not content or not content.strip():
            return None

        return ExtractedContent(
            text=content,
            source_type="url",
            title=title or url,
            metadata={
                "url": url,
                "via": "jina",
                "content_length": len(content),
            },
        )
    except Exception as exc:
        logger.debug("Jina Reader failed for %s: %s", url, exc)
        return None
