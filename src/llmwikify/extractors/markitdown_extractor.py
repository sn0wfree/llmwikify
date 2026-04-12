"""MarkItDown unified extractor for Office documents, images, and more.

Wraps Microsoft's MarkItDown library to convert various file formats
to Markdown. Falls back to existing extractors when MarkItDown is
not available or fails.

Supported formats (when markitdown[all] is installed):
- PDF (text + OCR via markitdown-ocr plugin)
- Word (.docx, .doc)
- Excel (.xlsx, .xls)
- PowerPoint (.pptx, .ppt)
- Images (.jpg, .png, .gif, etc.) with LLM vision descriptions
- Audio (.mp3, .wav) with speech transcription
- HTML (better than regex-based extraction)
- CSV, JSON, XML
- EPub, ZIP, Outlook (.msg)
"""

from pathlib import Path
from typing import Optional, Dict, Any, Set

from .base import ExtractedContent


# All file extensions handled by MarkItDown
MARKITDOWN_FORMATS: Set[str] = {
    ".pdf",
    ".docx", ".doc",
    ".xlsx", ".xls",
    ".pptx", ".ppt",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg",
    ".mp3", ".wav", ".m4a",
    ".html", ".htm",
    ".csv", ".json", ".xml",
    ".epub",
    ".zip",
    ".msg",
}


class MarkItDownExtractor:
    """Wrapper around MarkItDown with graceful fallback support.

    Usage:
        extractor = MarkItDownExtractor()
        if extractor.available:
            result = extractor.convert(path)
        else:
            # Fallback to existing extractors
            pass
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._md: Optional[Any] = None
        self._available: bool = False
        self._config = config
        self._init_markitdown()

    @property
    def available(self) -> bool:
        return self._available

    def _init_markitdown(self) -> None:
        """Initialize MarkItDown with optional LLM client for image OCR."""
        try:
            from markitdown import MarkItDown
        except ImportError:
            return

        # Try to configure LLM client for image descriptions / OCR
        llm_client = None
        llm_model = None

        if self._config and self._config.get("llm", {}).get("enabled"):
            try:
                from ..llm_client import LLMClient
                llm_client = LLMClient.from_config(self._config)
                llm_model = self._config["llm"].get("model", "gpt-4o")
            except Exception:
                pass

        try:
            if llm_client:
                self._md = MarkItDown(
                    enable_plugins=False,
                    llm_client=llm_client,
                    llm_model=llm_model,
                )
            else:
                self._md = MarkItDown(enable_plugins=False)
            self._available = True
        except Exception:
            self._available = False

    def convert(self, path: Path) -> Optional[ExtractedContent]:
        """Convert a file to Markdown using MarkItDown.

        Args:
            path: Path to the file to convert.

        Returns:
            ExtractedContent on success, None if MarkItDown is unavailable
            or conversion fails.
        """
        if not self._available or self._md is None:
            return None

        if not path.exists():
            return None

        try:
            result = self._md.convert(str(path))
            text_content = result.text_content

            if not text_content or not text_content.strip():
                return None

            title = self._extract_title(text_content, path)
            ext = path.suffix.lower()

            return ExtractedContent(
                text=text_content,
                source_type=_ext_to_source_type(ext),
                title=title,
                metadata={
                    "file_path": str(path),
                    "converter": "markitdown",
                    "extension": ext,
                },
            )
        except Exception:
            return None

    @staticmethod
    def _extract_title(text: str, path: Path) -> str:
        """Extract a title from the first heading or use filename."""
        import re

        # Try to find first markdown heading
        heading_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if heading_match:
            return heading_match.group(1).strip()

        # Try to find first non-empty line that looks like a title
        for line in text.split('\n')[:10]:
            stripped = line.strip()
            if stripped and not stripped.startswith('---') and len(stripped) > 3:
                return stripped[:100]

        return path.stem.replace('-', ' ').replace('_', ' ').title()


def _ext_to_source_type(ext: str) -> str:
    """Map file extension to source_type string."""
    type_map = {
        ".pdf": "pdf",
        ".docx": "docx", ".doc": "doc",
        ".xlsx": "xlsx", ".xls": "xls",
        ".pptx": "pptx", ".ppt": "ppt",
        ".jpg": "image", ".jpeg": "image", ".png": "image",
        ".gif": "image", ".bmp": "image", ".tiff": "image",
        ".tif": "image", ".webp": "image", ".svg": "image",
        ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
        ".html": "html", ".htm": "html",
        ".csv": "csv", ".json": "json", ".xml": "xml",
        ".epub": "epub",
        ".zip": "zip",
        ".msg": "outlook",
    }
    return type_map.get(ext, "text")
