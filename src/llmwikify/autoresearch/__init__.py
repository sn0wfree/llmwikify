"""AutoResearch: 6-step framework ReAct engine.

Independent top-level project that integrates a structured reasoning
framework (clarify → evidence → reasoning → structure → conclusion →
checklist) on top of a copy of the base research engine. Does not import
from llmwikify.agent.backend.research.
"""

from __future__ import annotations

from .clarifier import ResearchClarifier
from .config import DEFAULT_SIX_STEP_CONFIG, merge_six_step_config
from .engine import ResearchEngine
from .quality_gate import GateResult, QualityGate
from .reasoning_checker import ReasoningChecker
from .retry_managers import (
    DBRetryManager,
    LLMRetryManager,
    StageRetryManager,
    retry_async,
)
from .source_filter import SourceFilter
from .state import (
    ActionMetrics,
    MetricsCollector,
    ResearchState,
    SessionMetrics,
    VALID_TRANSITIONS,
)
from .structure_validator import StructureValidator

__all__ = [
    "ResearchEngine",
    "ResearchState",
    "ResearchClarifier",
    "DEFAULT_SIX_STEP_CONFIG",
    "merge_six_step_config",
    "VALID_TRANSITIONS",
    "ActionMetrics",
    "MetricsCollector",
    "SessionMetrics",
    "GateResult",
    "QualityGate",
    "ReasoningChecker",
    "SourceFilter",
    "StructureValidator",
    "StageRetryManager",
    "LLMRetryManager",
    "DBRetryManager",
    "retry_async",
]
