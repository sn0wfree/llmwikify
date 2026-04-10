"""Web URL extractor."""

from typing import Optional
from .base import ExtractedContent


def _extract_url(url: str) -> ExtractedContent:
    """Extract article content from a web URL using trafilatura."""
    try:
        import trafilatura
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="url",
            title=url,
            metadata={"error": "trafilatura not installed. Install with: pip install trafilatura"}
        )
    
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ExtractedContent(
                text="",
                source_type="url",
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
        
    except Exception as e:
        return ExtractedContent(
            text="",
            source_type="url",
            title=url,
            metadata={"error": f"Failed to extract from {url}: {e}"},
        )


# Export with consistent name
extract_url = _extract_url
