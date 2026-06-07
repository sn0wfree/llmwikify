"""PDF file extractor."""

from pathlib import Path

from .base import ExtractedContent


def _extract_pdf(path: Path) -> ExtractedContent:
    """Extract text from a PDF file using pymupdf."""
    try:
        import pymupdf
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="error",
            title=path.stem,
            metadata={"error": "pymupdf not installed. Install with: pip install pymupdf"}
        )

    doc = pymupdf.open(path)
    pages = []
    page_count = len(doc)

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text()
        pages.append(f"--- Page {page_num + 1} ---\n{text}")

    doc.close()

    full_text = "\n\n".join(pages)

    # Try to extract title from first page
    first_page_title = ""
    if pages:
        first_lines = pages[0].split('\n')[:5]
        for line in first_lines:
            if line.strip() and not line.startswith('---'):
                first_page_title = line.strip()
                break

    return ExtractedContent(
        text=full_text,
        source_type="pdf",
        title=first_page_title or path.stem,
        metadata={
            "file_path": str(path),
            "page_count": page_count,
        },
    )


# Export with consistent name
extract_pdf = _extract_pdf
