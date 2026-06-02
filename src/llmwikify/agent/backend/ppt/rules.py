"""PPT Generator - Rules engine for content_type to layout mapping."""

from typing import Dict, Any, List, Optional


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
        bullets: List[str] = content.get("bullets") or []
        count = len(bullets)
        if count <= 5:
            return "bullets"
        return "two_column"  # More than 5 items → split into columns
    
    if content_type == "data":
        chart_data = content.get("chart_data") or {}
        values = chart_data.get("values", [])
        if len(values) >= 3:
            return "chart"
        return "bullets"  # Too few data points for a chart
    
    # Fallback
    return "title_content"


def validate_content_for_layout(content_type: str, layout: str, content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate content and fill in missing required fields for the assigned layout.
    
    Returns the content dict with missing fields set to safe defaults.
    """
    # Ensure bullets is a list of strings
    if layout == "bullets" or layout == "two_column":
        bullets = content.get("bullets")
        if bullets is None:
            content["bullets"] = []
        elif not isinstance(bullets, list):
            content["bullets"] = [str(bullets)]

    # Ensure two_column has left/right with correct shape
    if layout == "two_column":
        for side in ("left", "right"):
            val = content.get(side)
            if val is None:
                content[side] = {"heading": "", "items": []}
            elif isinstance(val, dict):
                if "items" not in val or not isinstance(val["items"], list):
                    val["items"] = []
                if "heading" not in val or not isinstance(val["heading"], str):
                    val["heading"] = ""
            else:
                content[side] = {"heading": str(val), "items": []}

        # v0.6.2.patch1: Fallback — LLM sometimes returns flat bullets for
        # comparison/bullets content_type (e.g., "理论机制解析" with
        # content_type=comparison but output uses bullets). Without this,
        # both left.items and right.items stay empty, and the frontend
        # TwoColumnSlide renders two empty gray boxes. Split bullets in
        # half to recover.
        left_items = content["left"].get("items") or []
        right_items = content["right"].get("items") or []
        if not left_items and not right_items:
            bullets = content.get("bullets") or []
            if bullets:
                mid = (len(bullets) + 1) // 2  # odd count → left heavier
                content["left"]["items"] = bullets[:mid]
                content["right"]["items"] = bullets[mid:]
                # Clear bullets to avoid double-display
                content["bullets"] = []

    # Ensure chart has valid structure
    if layout == "chart":
        if content.get("chart_type") is None:
            content["chart_type"] = "bar"
        chart_data = content.get("chart_data")
        if chart_data is None:
            content["chart_data"] = {"labels": [], "values": []}
        elif isinstance(chart_data, dict):
            if not isinstance(chart_data.get("labels"), list):
                chart_data["labels"] = []
            if not isinstance(chart_data.get("values"), list):
                chart_data["values"] = []

    # Ensure quote has text and author
    if layout == "quote":
        if content.get("text") is None or not isinstance(content["text"], str):
            content["text"] = ""
        if content.get("author") is None or not isinstance(content["author"], str):
            content["author"] = ""

    # Ensure title_content has content string
    if layout == "title_content":
        c = content.get("content")
        if c is None:
            content["content"] = ""
        elif not isinstance(c, str):
            content["content"] = str(c)

    return content
