"""Backtest stage: runs QuantNodes PipelineRunner."""
from __future__ import annotations

from .base import Stage, StageContext


class BacktestStage(Stage):
    name = "backtest"

    def execute(self, ctx: StageContext) -> StageContext:
        # Stub
        return ctx
