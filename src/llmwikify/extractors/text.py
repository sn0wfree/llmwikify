import re

"""Text and HTML file extractors."""

from pathlib import Path

from .base import ExtractedContent


def _extract_text_file(path: Path) -> ExtractedContent:
    """Extract content from a plain text or markdown file."""
    content = path.read_text()

    # Try to get title from first heading
    heading_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    title = heading_match.group(1).strip() if heading_match else path.stem

    return ExtractedContent(
        text=content,
        source_type="markdown" if path.suffix == ".md" else "text",
        title=title,
        metadata={"file_path": str(path)},
    )


def _extract_html_file(path: Path) -> ExtractedContent:
    """Extract content from a local HTML file."""
    content = path.read_text()

    # Simple HTML to text conversion
    text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Try to get title
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else path.stem

    return ExtractedContent(
        text=text,
        source_type="html",
        title=title,
        metadata={"file_path": str(path)},
    )


# Export with consistent names
extract_text_file = _extract_text_file
extract_html_file = _extract_html_file
