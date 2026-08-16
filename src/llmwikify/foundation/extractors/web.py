"""Web URL extractor."""

import concurrent.futures
import logging

import requests

from ..utils import is_safe_url
from .base import ExtractedContent

logger = logging.getLogger(__name__)

# Default timeout for URL fetching (connect, read)
FETCH_TIMEOUT = (10, 30)  # (connect_timeout, read_timeout)

# ThreadPoolExecutor for running blocking trafilatura calls with timeout
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _fetch_with_timeout(url: str, timeout: tuple[int, int] = FETCH_TIMEOUT) -> str | None:
    """Fetch URL content with explicit timeout using requests."""
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)",
        }, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except (requests.RequestException, Exception):
        return None


def _extract_url(url: str, timeout: tuple[int, int] = FETCH_TIMEOUT) -> ExtractedContent:
    """Extract article content from a web URL.

    Fallback chain: trafilatura → Jina Reader → raw HTML.
    """
    if not is_safe_url(url):
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"URL blocked by SSRF protection: {url}"}
        )

    # Try trafilatura first
    result = _extract_url_trafilatura(url, timeout)
    if result and result.text and len(result.text.strip()) > 100:
        return result

    # Fallback to Jina Reader (handles JS-rendered SPAs, better extraction)
    from .jina import extract_via_jina
    jina_result = extract_via_jina(url)
    if jina_result and jina_result.text and len(jina_result.text.strip()) > 100:
        logger.info("Extracted via Jina Reader: %s", url[:80])
        return jina_result

    # Final fallback: return whatever trafilatura got (even if short)
    return result or ExtractedContent(
        text="",
        source_type="error",
        title=url,
        metadata={"error": f"Failed to extract from {url}"},
    )


def _extract_url_trafilatura(url: str, timeout: tuple[int, int] = FETCH_TIMEOUT) -> ExtractedContent | None:
    """Extract using trafilatura."""
    try:
        import trafilatura
    except ImportError:
        return None

    try:
        future = _executor.submit(trafilatura.fetch_url, url)
        try:
            downloaded = future.result(timeout=15)
        except concurrent.futures.TimeoutError:
            future.cancel()
            downloaded = None

        if not downloaded:
            downloaded = _fetch_with_timeout(url, timeout)

        if not downloaded:
            return None

        text = trafilatura.extract(downloaded)

        import re
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', downloaded, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else url

        return ExtractedContent(
            text=text or "",
            source_type="url",
            title=title,
            metadata={"url": url},
        )

    except (ConnectionError, TimeoutError, ValueError, OSError):
        return None


# Export with consistent name
extract_url = _extract_url
