"""Base extractor functions and data classes."""

import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class ExtractedContent:
    """Result of extracting content from a source."""
    text: str
    source_type: str
    title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def content_length(self) -> int:
        return len(self.text)


@dataclass
class Link:
    """A wiki link."""
    target: str
    section: str = ""
    display: str = ""


# YouTube URL patterns
_YOUTUBE_PATTERNS = (
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)",
)


def detect_source_type(source: str) -> str:
    """Detect whether a source is a URL, YouTube link, or file (by extension)."""
    if any(re.search(p, source) for p in _YOUTUBE_PATTERNS):
        return "youtube"
    
    if source.startswith(("http://", "https://")):
        return "url"
    
    ext = Path(source).suffix.lower()
    return {
        ".pdf": "pdf",
        ".md": "markdown",
        ".txt": "text",
        ".html": "html",
        ".htm": "html",
    }.get(ext, "text")


def extract(source: str, wiki_root: Optional[Path] = None) -> ExtractedContent:
    """Extract content from any supported source. Auto-detects type.
    
    Args:
        source: File path (absolute or relative) or URL.
        wiki_root: Wiki root directory for resolving relative paths.
    
    Returns:
        ExtractedContent with the extracted text and metadata.
    """
    source_type = detect_source_type(source)
    
    if source_type in ("youtube", "url"):
        from .youtube import extract_youtube
        from .web import extract_url
        return extract_youtube(source) if source_type == "youtube" else extract_url(source)
    
    # It's a file — resolve the path
    path = Path(source)
    if not path.is_absolute() and wiki_root:
        path = wiki_root / path
    
    if not path.exists():
        return ExtractedContent(
            text="",
            source_type="error",
            title=str(path),
            metadata={"error": f"File not found: {source}"}
        )
    
    # Dispatch to file extractors
    if source_type == "pdf":
        from .pdf import extract_pdf
        return extract_pdf(path)
    elif source_type in ("markdown", "text", "html"):
        from .text import extract_text_file, extract_html_file
        return extract_html_file(path) if source_type == "html" else extract_text_file(path)
    else:
        return extract_text_file(path)
