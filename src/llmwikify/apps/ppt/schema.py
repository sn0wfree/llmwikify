"""PPT Generator - JSON Schema definitions for outline and content."""


from pydantic import BaseModel, Field


class OutlinePage(BaseModel):
    """Single page in an outline."""
    page: int = Field(..., description="Page number (1-indexed)")
    content_type: str = Field(..., description="Semantic content type: intro, section, bullets, comparison, data, quote, summary")
    title: str = Field(..., description="Slide title")
    description: str = Field(..., description="Brief description of what this slide should cover")


class Outline(BaseModel):
    """Presentation outline (Step 1 output)."""
    title: str = Field(..., description="Presentation title")
    subtitle: str | None = Field(None, description="Presentation subtitle")
    pages: list[OutlinePage] = Field(..., description="List of slide outlines")


class OutlineRequest(BaseModel):
    """Request to generate an outline."""
    topic: str = Field(..., description="Presentation topic")
    num_slides: int = Field(8, ge=3, le=20, description="Number of slides (3-20)")
    language: str = Field("zh", description="Language: zh or en")


class OutlineResponse(BaseModel):
    """Response containing the generated outline."""
    outline: Outline


class GenerateRequest(BaseModel):
    """Request to generate content based on outline (Step 2)."""
    outline: Outline = Field(..., description="The outline to generate content for")
    theme: str = Field("professional", description="Theme name")
    language: str = Field("zh", description="Language: zh or en")
    source_type: str | None = Field(
        None, description="v0.5: Source of outline — 'topic'|'research'|'chat'"
    )
    source_id: str | None = Field(
        None, description="v0.5: ID of source research/chat session"
    )


# Content types for slides
CONTENT_TYPES = ["intro", "section", "bullets", "comparison", "data", "quote", "summary"]

# Layout types for slides
LAYOUT_TYPES = ["title", "section", "bullets", "title_content", "two_column", "chart", "quote"]


class SlideContent(BaseModel):
    """Content for a single slide."""
    id: str = Field(..., description="Unique slide ID")
    layout: str = Field(..., description="Layout type")
    title: str = Field(..., description="Slide title")
    subtitle: str | None = Field(None, description="Subtitle (for intro/title layouts)")
    content: str | None = Field(None, description="Main content text")
    bullets: list[str] | None = Field(None, description="Bullet points")
    left: dict | None = Field(None, description="Left column (for two_column layout)")
    right: dict | None = Field(None, description="Right column (for two_column layout)")
    chart_type: str | None = Field(None, description="Chart type: bar, line, pie")
    chart_data: dict | None = Field(None, description="Chart data with labels and values")
    text: str | None = Field(None, description="Quote text")
    author: str | None = Field(None, description="Quote author")
    image: str | None = Field(None, description="Image URL or base64")
    # Extended layout fields (v0.7)
    swot: dict | None = Field(None, description="SWOT data: {strengths:[], weaknesses:[], opportunities:[], threats:[]}")
    table_headers: list[str] | None = Field(None, description="Table headers")
    table_rows: list[list[str]] | None = Field(None, description="Table data rows")
    events: list[dict] | None = Field(None, description="Timeline events: [{date, title, description}]")
    kpi_items: list[dict] | None = Field(None, description="KPI items: [{label, value, trend}]")
    central_topic: str | None = Field(None, description="Mindmap center topic")
    branches: list[dict] | None = Field(None, description="Mindmap branches: [{name, children:[{name}]}]")
    steps: list[dict] | None = Field(None, description="Process steps: [{title, description}]")
    images: list[dict] | None = Field(None, description="Gallery images: [{url, caption}]")
    html: str | None = Field(None, description="Custom HTML content for unknown layouts")


class ThemeColors(BaseModel):
    """Color scheme for a theme (v0.5 legacy 5-color palette).

    Kept for backward compatibility — v0.6.1 themes expose full design tokens
    via `tokens` instead. The 5 fields are still populated by `to_legacy_colors()`
    so the .pptx exporter and any other legacy consumer continues to work.
    """
    primary: str = Field(..., description="Primary color (hex)")
    secondary: str = Field(..., description="Secondary color (hex)")
    background: str = Field(..., description="Background color (hex)")
    text: str = Field(..., description="Text color (hex)")
    accent: str = Field(..., description="Accent color (hex)")


class Theme(BaseModel):
    """Presentation theme.

    v0.6.1 design:
    - `id` is the canonical theme identifier (e.g. "minimal-white")
    - `name_zh` / `name_en` are user-facing labels
    - `category` is one of: minimal|soft|warm|cool|dark|colorful|tech|brand|design|retro
    - `description` is a 50-100 char usage hint
    - `tokens` is a flat dict of CSS custom properties (color-*, font-*, radius-*, etc.)
    - `colors` is the legacy 5-color palette derived from tokens for backward compat

    Themes are adapted from https://github.com/lewislulu/html-ppt-skill (MIT, 5.4k ⭐).
    """
    id: str = Field(..., description="Canonical theme id (e.g. 'minimal-white')")
    name: str = Field(..., description="Display label (English, legacy alias for name_en)")
    name_zh: str = Field("", description="Chinese display label")
    name_en: str = Field("", description="English display label")
    label: str = Field("", description="Legacy display label alias")
    category: str = Field("minimal", description="Theme category for grouping")
    description: str = Field("", description="Usage hint (50-100 chars)")
    tokens: dict = Field(default_factory=dict, description="Full design tokens (color-*, font-*, radius-*, shadow-*, gradient-*)")
    colors: ThemeColors = Field(..., description="Legacy 5-color palette (auto-derived from tokens)")
    attribution: str = Field("Based on html-ppt-skill (MIT, © 2026 lewislulu)", description="License attribution")


class Presentation(BaseModel):
    """Complete presentation data."""
    title: str = Field(..., description="Presentation title")
    subtitle: str | None = Field(None, description="Presentation subtitle")
    theme: Theme
    slides: list[SlideContent]
    source: dict = Field(default_factory=lambda: {"type": "topic"})


class GenerateResponse(BaseModel):
    """Response containing the generated presentation."""
    presentation: Presentation
    model_used: str = Field(..., description="LLM model used")
    generation_time_ms: int = Field(..., description="Generation time in milliseconds")


class FromResearchRequest(BaseModel):
    """Request to generate PPT from research results."""
    research_id: str = Field(..., description="Research session ID")
    theme: str = Field("professional", description="Theme name")
    language: str = Field("zh", description="Language: zh or en")


class FromChatRequest(BaseModel):
    """Request to generate PPT from chat conversation."""
    chat_session_id: str = Field(..., description="Chat session ID")
    theme: str = Field("professional", description="Theme name")
    language: str = Field("zh", description="Language: zh or en")


class FromSourceResponse(BaseModel):
    """Response from generating outline from research or chat."""
    outline: Outline
    source_summary: str = Field(..., description="Summary of the source content")
    source_count: int = Field(..., description="Number of source items (messages or sources)")
