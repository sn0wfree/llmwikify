"""PPT Generator module."""

from .engine import PPTEngine
from .schema import (
    CONTENT_TYPES,
    GenerateRequest,
    GenerateResponse,
    FromChatRequest,
    FromResearchRequest,
    FromSourceResponse,
    LAYOUT_TYPES,
    Outline,
    OutlinePage,
    OutlineRequest,
    OutlineResponse,
    Presentation,
    SlideContent,
    Theme,
    ThemeColors,
)
from .themes import get_theme, list_themes
from .harness import SlideHarness
from .chat_engine import PPTChatEngine
from .chat_router import PPTChatRouter

__all__ = [
    "PPTEngine",
    "CONTENT_TYPES",
    "LAYOUT_TYPES",
    "Outline",
    "OutlinePage",
    "OutlineRequest",
    "OutlineResponse",
    "GenerateRequest",
    "GenerateResponse",
    "FromResearchRequest",
    "FromChatRequest",
    "FromSourceResponse",
    "Presentation",
    "SlideContent",
    "Theme",
    "ThemeColors",
    "get_theme",
    "list_themes",
    "SlideHarness",
    "PPTChatEngine",
    "PPTChatRouter",
]
