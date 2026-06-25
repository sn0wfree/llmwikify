"""web_fetch_skill — fetch a single URL and extract readable text.

This is the 27th base action exposed to the LLM via the Skill
framework. It complements ``web_search`` (which returns result
listings) by retrieving the actual content of a page.

Actions
-------

  - ``fetch_url(url, max_chars)`` — GET a URL, extract page title
    and readable text (HTML stripped). Returns the first
    ``max_chars`` characters of stripped text plus metadata.

Configuration
-------------

  - ``web_fetch_max_chars``: default 2000 (cap for the returned
    ``content`` field). Hard-capped at 50000 to avoid OOM.
  - ``web_fetch_timeout_seconds``: default 10.0.

Why this exists
---------------

``web_fetch`` was previously listed in
``apps/chat/agent/spec.py:DEFAULT_COMPACTABLE_TOOLS`` but had no
implementation anywhere in the codebase. This skill fills that
gap. It uses httpx (already a ``[web]`` extra dependency) for
async HTTP and a tiny HTMLParser-based extractor for the title.

The handler is sync-friendly: ``fetch_url_sync`` wraps the async
implementation in ``asyncio.run`` for callers that run in a sync
context (e.g. subagent_worker.py tool loop).
"""

from __future__ import annotations

import asyncio
import logging
import re
from html.parser import HTMLParser

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── HTML helpers ────────────────────────────────────────────────


class _TitleExtractor(HTMLParser):
    """Tiny HTML parser that captures the contents of ``<title>``."""

    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()


def _extract_title(html: str) -> str:
    parser = _TitleExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — defensive: malformed HTML
        return ""
    return parser.title[:200]


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HREF_RE = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _strip_html(html: str) -> str:
    """Strip script/style blocks then all tags. Collapse whitespace."""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = _WS_RE.sub(" ", cleaned)
    return cleaned.strip()


# ─── Core fetcher ────────────────────────────────────────────────


DEFAULT_MAX_CHARS = 2000
MAX_HARD_CAP = 50000
DEFAULT_TIMEOUT = 10.0
USER_AGENT = "llmwikify/0.41 (+web_fetch)"


async def fetch_url(
    url: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Fetch a URL and return ``{url, status, title, content, length, truncated}``.

    On error returns ``{"error": "...", "url": url}`` so callers
    (LLM tool loop or skill handler) can feed the error back as a
    tool result without crashing the agent.
    """
    try:
        import httpx
    except ImportError as e:
        return {"error": f"httpx required: {e!r}", "url": url}

    if not url or not isinstance(url, str):
        return {"error": "url is required", "url": url}

    cap = min(max_chars, MAX_HARD_CAP)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "url": url}

    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}", "url": url, "status": resp.status_code}

    try:
        html = resp.text
    except Exception as e:  # noqa: BLE001
        return {"error": f"decode failed: {e!r}", "url": url, "status": resp.status_code}

    title = _extract_title(html)
    full_text = _strip_html(html)
    truncated = len(full_text) > cap
    content = full_text[:cap]

    return {
        "url": url,
        "status": resp.status_code,
        "title": title,
        "content": content,
        "length": len(full_text),
        "truncated": truncated,
    }


def fetch_url_sync(
    url: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Sync wrapper for use in sync tool loops (subagent_worker)."""
    return asyncio.run(fetch_url(url, max_chars, timeout))


# ─── Skill handler ───────────────────────────────────────────────


async def _fetch_url_handler(args: dict, ctx: SkillContext) -> SkillResult:
    """Skill handler — same shape as web_search's handlers."""
    url = (args.get("url") or "").strip()
    if not url:
        return SkillResult.fail("url is required")

    max_chars = args.get("max_chars")
    if max_chars is None:
        max_chars = (ctx.config or {}).get("web_fetch_max_chars", DEFAULT_MAX_CHARS)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        return SkillResult.fail(f"max_chars must be int, got {max_chars!r}")
    if max_chars < 1:
        return SkillResult.fail("max_chars must be >= 1")
    if max_chars > MAX_HARD_CAP:
        max_chars = MAX_HARD_CAP

    timeout = float((ctx.config or {}).get("web_fetch_timeout_seconds", DEFAULT_TIMEOUT))

    try:
        payload = await fetch_url(url, max_chars=max_chars, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        logger.warning("web_fetch failed for %s: %s", url[:80], e)
        return SkillResult.fail(f"web_fetch failed: {e!r}")

    if "error" in payload:
        return SkillResult.fail(payload["error"], **{
            k: v for k, v in payload.items() if k != "error"
        })

    return SkillResult.ok(payload)


# ─── Skill declaration ───────────────────────────────────────────


class WebFetchSkill(Skill):
    """Fetch a URL and extract readable text."""

    name = "web_fetch"
    description = (
        "Fetch a single URL via HTTP GET and return its title plus "
        "extracted text (HTML stripped, scripts/styles removed). "
        "Complements web_search: use search_web to find candidate "
        "URLs, then fetch_url to read a specific page."
    )
    actions = {
        "fetch_url": SkillAction(
            name="fetch_url",
            description=(
                "Fetch a URL and return its page title plus text content "
                "(HTML stripped, first ``max_chars`` characters, default "
                "2000). Returns status code, content length, and a "
                "``truncated`` flag. Use this when the user asks to read "
                "or summarize a specific URL, or after web_search "
                "returns candidate links."
            ),
            handler=_fetch_url_handler,
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "HTTP(S) URL to fetch (required).",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": (
                            "Max characters of text to return "
                            "(default 2000, hard-capped at 50000)."
                        ),
                        "default": 2000,
                        "minimum": 1,
                        "maximum": 50000,
                    },
                },
                "required": ["url"],
            },
        ),
    }


web_fetch_skill = WebFetchSkill()


__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_TIMEOUT",
    "MAX_HARD_CAP",
    "WebFetchSkill",
    "fetch_url",
    "fetch_url_sync",
    "web_fetch_skill",
]
