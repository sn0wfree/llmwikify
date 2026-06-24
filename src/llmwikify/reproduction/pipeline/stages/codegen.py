"""Code generation stage: LLM produces factor code."""
from __future__ import annotations

from .base import Stage, StageContext


class CodegenStage(Stage):
    name = "codegen"
    required_prompts = ["code_gen"]

    def execute(self, ctx: StageContext) -> StageContext:
        # Stub: will be wired in Phase 14F
        return ctx
