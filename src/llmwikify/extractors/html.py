def _extract_html_file(path: Path) -> ExtractedContent:
    """Extract content from a local HTML file."""
    raw_html = path.read_text(errors="replace")
    text = _html_to_text(raw_html)
    
    title = path.stem.replace("-", " ").replace("_", " ").title()
    title_match = re.search(r"<title>(.+?)</title>", raw_html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
    
    return ExtractedContent(
        text=text,
        source_type="html",
        title=title,
        metadata={"file_name": path.name},
    )

