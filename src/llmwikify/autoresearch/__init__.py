"""AutoResearch: 6-step framework ReAct engine.

Independent top-level project that integrates a structured reasoning
framework (clarify → evidence → reasoning → structure → conclusion →
checklist) on top of a copy of the base research engine. Does not import
from llmwikify.agent.backend.research.
"""

from __future__ import annotations

from .clarifier import ResearchClarifier
from .config import DEFAULT_SIX_STEP_CONFIG, merge_six_step_config
from .engine import ResearchEngine, ResearchState, VALID_TRANSITIONS

__all__ = [
    "ResearchEngine",
    "ResearchState",
    "ResearchClarifier",
    "DEFAULT_SIX_STEP_CONFIG",
    "merge_six_step_config",
    "VALID_TRANSITIONS",
]
