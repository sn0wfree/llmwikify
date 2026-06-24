"""Persist factor stage: writes YAML + DB records."""
from __future__ import annotations

from .base import Stage, StageContext


class PersistFactorStage(Stage):
    name = "persist_factor"

    def execute(self, ctx: StageContext) -> StageContext:
        # Stub
        return ctx
