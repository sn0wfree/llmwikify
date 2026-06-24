"""Paper understanding stage: parses formulas from track signals."""
from __future__ import annotations

from .base import Stage, StageContext


class PaperUnderstandingStage(Stage):
    name = "paper_understanding"
    required_prompts = ["track_a", "track_b"]

    def execute(self, ctx: StageContext) -> StageContext:
        # Stub: will be wired in Phase 14F
        return ctx
