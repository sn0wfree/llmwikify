"""PPTChat Harness - Deterministic slide operations (no LLM needed).

Handles mechanical operations that can be solidified:
- Delete slide
- Move slide
- Duplicate slide
- Change theme
- Change layout
- Undo

All operations are pure data transformations with <50ms latency.
"""

from __future__ import annotations

import copy
import logging
from typing import List, Optional

from .schema import Presentation, SlideContent, Theme
from .themes import get_theme

logger = logging.getLogger(__name__)

# Fields compatible with each layout type
LAYOUT_FIELDS = {
    "title": ["subtitle"],
    "section": ["subtitle"],
    "bullets": ["bullets"],
    "title_content": ["content"],
    "two_column": ["left", "right"],
    "chart": ["chart_type", "chart_data"],
    "quote": ["text", "author"],
    "image_text": ["image", "content"],
    "table": ["table_headers", "table_rows"],
    "timeline": ["events"],
    "kpi_grid": ["kpi_items"],
    "mindmap": ["central_topic", "branches"],
    "process": ["steps"],
    "gallery": ["images"],
    "swot": ["swot"],
}

# All optional fields that can be cleared when changing layout
# (must match SlideContent model fields — currently 7 core layouts)
ALL_OPTIONAL_FIELDS = [
    "subtitle", "content", "bullets", "left", "right",
    "chart_type", "chart_data", "text", "author", "image",
]


class SlideHarness:
    """Deterministic slide operations with undo support.

    Usage:
        harness = SlideHarness(presentation)
        result = harness.delete_slide(2)
        result = harness.undo()  # restore
    """

    def __init__(self, presentation: Presentation):
        self.original = presentation
        self.slides = [s.model_copy(deep=True) for s in presentation.slides]
        self.theme = presentation.theme
        self.history: List[List[SlideContent]] = []
        self._max_history = 20

    def _save_history(self) -> None:
        """Push current state to undo stack."""
        self.history.append([s.model_copy(deep=True) for s in self.slides])
        if len(self.history) > self._max_history:
            self.history.pop(0)

    def _build(self) -> Presentation:
        """Build Presentation from current state."""
        return Presentation(
            title=self.original.title,
            subtitle=self.original.subtitle,
            theme=self.theme,
            slides=self.slides,
            source=self.original.source,
        )

    def _clear_incompatible_fields(self, slide: SlideContent, new_layout: str) -> None:
        """Remove fields that don't belong to the new layout."""
        keep = set(LAYOUT_FIELDS.get(new_layout, []))
        for field in ALL_OPTIONAL_FIELDS:
            if field not in keep:
                setattr(slide, field, None)

    # ─── Operations ───────────────────────────────────────────

    def delete_slide(self, index: int) -> Presentation:
        """Delete slide at index."""
        self._save_history()
        if 0 <= index < len(self.slides):
            self.slides.pop(index)
        return self._build()

    def move_slide(self, from_idx: int, to_idx: int) -> Presentation:
        """Move slide from one position to another."""
        self._save_history()
        if (0 <= from_idx < len(self.slides)
                and 0 <= to_idx < len(self.slides)
                and from_idx != to_idx):
            slide = self.slides.pop(from_idx)
            self.slides.insert(to_idx, slide)
        return self._build()

    def duplicate_slide(self, index: int) -> Presentation:
        """Duplicate slide at index, insert after original."""
        self._save_history()
        if 0 <= index < len(self.slides):
            copy_slide = self.slides[index].model_copy(deep=True)
            copy_slide.id = f"{copy_slide.id}-dup"
            self.slides.insert(index + 1, copy_slide)
        return self._build()

    def change_theme(self, theme_id: str) -> Presentation:
        """Switch to a different theme."""
        self._save_history()
        self.theme = get_theme(theme_id)
        return self._build()

    def change_layout(self, index: int, new_layout: str) -> Presentation:
        """Change layout type for a slide, clearing incompatible fields."""
        self._save_history()
        if 0 <= index < len(self.slides):
            slide = self.slides[index]
            slide.layout = new_layout
            self._clear_incompatible_fields(slide, new_layout)
        return self._build()

    def undo(self) -> Presentation:
        """Restore previous state."""
        if self.history:
            self.slides = self.history.pop()
        return self._build()

    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self.history) > 0

    def get_slide(self, index: int) -> Optional[SlideContent]:
        """Get slide at index (read-only)."""
        if 0 <= index < len(self.slides):
            return self.slides[index]
        return None

    def slide_count(self) -> int:
        """Return current slide count."""
        return len(self.slides)

    def to_dict(self) -> dict:
        """Serialize current state for DB persistence."""
        return {
            "slides": [s.model_dump() for s in self.slides],
            "theme_id": self.theme.id,
        }

    @classmethod
    def from_dict(cls, data: dict, original: Presentation) -> SlideHarness:
        """Restore from serialized state."""
        harness = cls(original)
        if "slides" in data:
            harness.slides = [SlideContent(**s) for s in data["slides"]]
        if "theme_id" in data:
            harness.theme = get_theme(data["theme_id"])
        return harness
