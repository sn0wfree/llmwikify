"""Base extractor functions and data classes."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExtractedContent:
    """Result of extracting content from a source."""
    text: str
    source_type: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

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

# ---------------------------------------------------------------------------
# Single source of truth: extension → (source_type, handlers)
#
# handlers is a list of extractor names to try in order:
#   "markitdown" — Microsoft MarkItDown (try first for rich formats)
#   "pdf"        — legacy pymupdf extractor
#   "text"       — plain/markdown text extractor
#   "html"       — legacy HTML extractor
#
# Extensions not listed here default to ("text", ["text"]).
# ---------------------------------------------------------------------------

_EXTRACTOR_REGISTRY: dict[str, tuple[str, list[str]]] = {
    # PDF — try MarkItDown first (OCR support), fallback to pymupdf
    ".pdf": ("pdf", ["markitdown", "pdf"]),
    # Office formats — MarkItDown only
    ".docx": ("docx", ["markitdown"]),
    ".doc": ("doc", ["markitdown"]),
    ".xlsx": ("xlsx", ["markitdown"]),
    ".xls": ("xls", ["markitdown"]),
    ".pptx": ("pptx", ["markitdown"]),
    ".ppt": ("ppt", ["markitdown"]),
    # Images — MarkItDown only (requires LLM vision)
    ".jpg": ("image", ["markitdown"]), ".jpeg": ("image", ["markitdown"]),
    ".png": ("image", ["markitdown"]), ".gif": ("image", ["markitdown"]),
    ".bmp": ("image", ["markitdown"]), ".tiff": ("image", ["markitdown"]),
    ".tif": ("image", ["markitdown"]), ".webp": ("image", ["markitdown"]),
    ".svg": ("image", ["markitdown"]),
    # Audio — MarkItDown only (requires speech transcription)
    ".mp3": ("audio", ["markitdown"]), ".wav": ("audio", ["markitdown"]),
    ".m4a": ("audio", ["markitdown"]),
    # HTML — try MarkItDown first, fallback to legacy html extractor
    ".html": ("html", ["markitdown", "html"]),
    ".htm": ("html", ["markitdown", "html"]),
    # Structured data — MarkItDown only
    ".csv": ("csv", ["markitdown"]),
    ".json": ("json", ["markitdown"]),
    ".xml": ("xml", ["markitdown"]),
    # E-book / archive / email — MarkItDown only
    ".epub": ("epub", ["markitdown"]),
    ".zip": ("zip", ["markitdown"]),
    ".msg": ("outlook", ["markitdown"]),
    # Plain text — legacy only (MarkItDown adds no value)
    ".md": ("markdown", ["text"]),
    ".markdown": ("markdown", ["text"]),
    ".txt": ("text", ["text"]),
}

# Derived: set of extensions handled by MarkItDown
MARKITDOWN_FORMATS: set[str] = {
    ext for ext, (_, handlers) in _EXTRACTOR_REGISTRY.items()
    if "markitdown" in handlers
}


def detect_source_type(source: str) -> str:
    """Detect whether a source is a URL, YouTube link, or file (by extension)."""
    if any(re.search(p, source) for p in _YOUTUBE_PATTERNS):
        return "youtube"

    if source.startswith(("http://", "https://")):
        return "url"

    ext = Path(source).suffix.lower()
    return _EXTRACTOR_REGISTRY.get(ext, ("text", ["text"]))[0]


def extract(source: str, wiki_root: Path | None = None) -> ExtractedContent:
    """Extract content from any supported source. Auto-detects type.

    Args:
        source: File path (absolute or relative) or URL.
        wiki_root: Wiki root directory for resolving relative paths.

    Returns:
        ExtractedContent with the extracted text and metadata.
    """
    source_type = detect_source_type(source)

    if source_type in ("youtube", "url"):
        from .web import extract_url
        from .youtube import extract_youtube
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

    ext = path.suffix.lower()
    _, handlers = _EXTRACTOR_REGISTRY.get(ext, ("text", ["text"]))

    # Try each handler in priority order
    for handler in handlers:
        if handler == "markitdown":
            from .markitdown_extractor import MarkItDownExtractor
            extractor = MarkItDownExtractor()
            result = extractor.convert(path)
            if result:
                return result
            # MarkItDown unavailable or failed — try next handler
        elif handler == "pdf":
            from .pdf import extract_pdf
            return extract_pdf(path)
        elif handler == "text":
            from .text import extract_text_file
            return extract_text_file(path)
        elif handler == "html":
            from .text import extract_html_file
            return extract_html_file(path)

    # No handler succeeded (shouldn't happen for registered extensions)
    return ExtractedContent(
        text="",
        source_type="error",
        title=str(path),
        metadata={"error": f"All extractors failed for '{ext}' files."}
    )
