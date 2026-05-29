"""Web URL extractor."""

import requests
from .base import ExtractedContent

# Default timeout for URL fetching (connect, read)
FETCH_TIMEOUT = (10, 30)  # (connect_timeout, read_timeout)


def _fetch_with_timeout(url: str, timeout: tuple[int, int] = FETCH_TIMEOUT) -> str | None:
    """Fetch URL content with explicit timeout using requests."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)",
        }, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except (requests.RequestException, Exception):
        return None


def _extract_url(url: str, timeout: tuple[int, int] = FETCH_TIMEOUT) -> ExtractedContent:
    """Extract article content from a web URL using trafilatura."""
    try:
        import trafilatura
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": "trafilatura not installed. Install with: pip install trafilatura"}
        )

    try:
        # Try trafilatura first (better content extraction)
        downloaded = trafilatura.fetch_url(url)

        # Fallback to requests with timeout if trafilatura fails
        if not downloaded:
            downloaded = _fetch_with_timeout(url, timeout)

        if not downloaded:
            return ExtractedContent(
                text="",
                source_type="error",
                title=url,
                metadata={"error": f"Failed to download {url}"}
            )

        text = trafilatura.extract(downloaded)

        # Try to get title from HTML
        import re
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', downloaded, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else url

        return ExtractedContent(
            text=text or "",
            source_type="url",
            title=title,
            metadata={"url": url},
        )

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"Failed to extract from {url}: {e}"},
        )


# Export with consistent name
extract_url = _extract_url
