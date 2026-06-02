"""PPT Generator - Rules engine for content_type to layout mapping."""

from typing import Dict, Any, List


# Fixed mapping: content_type → layout
TYPE_TO_LAYOUT: Dict[str, str] = {
    "intro": "title",
    "section": "section",
    "quote": "quote",
    "summary": "title_content",
    "comparison": "two_column",
}


def resolve_layout(content_type: str, content: Dict[str, Any]) -> str:
    """
    Map semantic content_type to structural layout.
    
    Args:
        content_type: The semantic type from LLM (intro, section, bullets, etc.)
        content: The actual content data for this slide
    
    Returns:
        The layout type to use for rendering
    """
    # Fixed mapping
    if content_type in TYPE_TO_LAYOUT:
        return TYPE_TO_LAYOUT[content_type]
    
    # Dynamic mapping based on content characteristics
    if content_type == "bullets":
        bullets: List[str] = content.get("bullets", [])
        count = len(bullets)
        if count <= 5:
            return "bullets"
        return "two_column"  # More than 5 items → split into columns
    
    if content_type == "data":
        chart_data = content.get("chart_data", {})
        values = chart_data.get("values", [])
        if len(values) >= 3:
            return "chart"
        return "bullets"  # Too few data points for a chart
    
    # Fallback
    return "title_content"


def validate_content_for_layout(content_type: str, layout: str, content: Dict[str, Any]) -> bool:
    """
    Validate that content is compatible with the assigned layout.
    
    Args:
        content_type: The semantic type
        layout: The assigned layout
        content: The content data
    
    Returns:
        True if valid, False otherwise
    """
    required_fields = {
        "title": [],
        "section": [],
        "bullets": ["bullets"],
        "title_content": ["content"],
        "two_column": ["left", "right"],
        "chart": ["chart_type", "chart_data"],
        "quote": ["text", "author"],
    }
    
    fields = required_fields.get(layout, [])
    for field in fields:
        if field not in content or content[field] is None:
            return False
    
    return True
