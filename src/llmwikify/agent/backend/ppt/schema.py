"""PPT Generator - JSON Schema definitions for outline and content."""

from typing import List, Optional
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
    subtitle: Optional[str] = Field(None, description="Presentation subtitle")
    pages: List[OutlinePage] = Field(..., description="List of slide outlines")


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


# Content types for slides
CONTENT_TYPES = ["intro", "section", "bullets", "comparison", "data", "quote", "summary"]

# Layout types for slides
LAYOUT_TYPES = ["title", "section", "bullets", "title_content", "two_column", "chart", "quote"]


class SlideContent(BaseModel):
    """Content for a single slide."""
    id: str = Field(..., description="Unique slide ID")
    layout: str = Field(..., description="Layout type")
    title: str = Field(..., description="Slide title")
    subtitle: Optional[str] = Field(None, description="Subtitle (for intro/title layouts)")
    content: Optional[str] = Field(None, description="Main content text")
    bullets: Optional[List[str]] = Field(None, description="Bullet points")
    left: Optional[dict] = Field(None, description="Left column (for two_column layout)")
    right: Optional[dict] = Field(None, description="Right column (for two_column layout)")
    chart_type: Optional[str] = Field(None, description="Chart type: bar, line, pie")
    chart_data: Optional[dict] = Field(None, description="Chart data with labels and values")
    text: Optional[str] = Field(None, description="Quote text")
    author: Optional[str] = Field(None, description="Quote author")
    image: Optional[str] = Field(None, description="Image URL or base64")


class ThemeColors(BaseModel):
    """Color scheme for a theme."""
    primary: str = Field(..., description="Primary color (hex)")
    secondary: str = Field(..., description="Secondary color (hex)")
    background: str = Field(..., description="Background color (hex)")
    text: str = Field(..., description="Text color (hex)")
    accent: str = Field(..., description="Accent color (hex)")


class Theme(BaseModel):
    """Presentation theme."""
    name: str = Field(..., description="Theme name")
    label: str = Field(..., description="Display label")
    colors: ThemeColors


class Presentation(BaseModel):
    """Complete presentation data."""
    title: str = Field(..., description="Presentation title")
    subtitle: Optional[str] = Field(None, description="Presentation subtitle")
    theme: Theme
    slides: List[SlideContent]
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
