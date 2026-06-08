"""L3 apps/chat/ — generic chat framework + research agent.

Per the 4-layer refactor (Sprint C, design doc §3.5), this
package is the L3 home for:

- **ResearchAgent** (the existing 6-step research engine
  from ``autoresearch/``, now relocated here)
- **ChatBase** (new) — generic chat framework: session/
  message management, streaming output, tool registration,
  LLM provider abstraction. Designed to be reused by
  ResearchAgent and future chat-driven apps.
- **Harness** (new) — eval framework: golden test cases,
  LLM-as-judge scoring, regression detection,
  ``@pytest.mark.harness`` integration.

Layout
------

    apps/chat/
    ├── (26 files git-mv'd from autoresearch/ — unchanged)
    ├── base.py            ← NEW: ChatBase (~150 LOC)
    ├── harness.py         ← NEW: Harness (~100 LOC)
    ├── research_agent.py  ← NEW: ResearchAgent(ChatBase), thin wrapper
    └── README.md          ← (moved from autoresearch/)

Per design decision D14, this is **NOT a full rewrite** of
the existing research code. The 26 relocated files are
preserved byte-for-byte. The 3 new files are thin wrappers
that expose a unified chat-style interface on top of the
existing engine.
"""
from .base import ChatBase, ChatMessage, ChatSession
from .clarifier import ResearchClarifier
from .config import DEFAULT_SIX_STEP_CONFIG, merge_six_step_config
from .engine import ResearchEngine, ResearchState  # re-exported below
from .gates import ResearchGates
from .eval_harness import CaseResult, GoldenCase, Harness, HarnessReport
from .db import AutoResearchDatabase, ChatDatabase
from .llm_step import LLMCallMetrics
from .state import MetricsCollector
from .quality_gate import GateResult, QualityGate
from .reasoning_checker import ReasoningChecker
from .report import ReportGenerator
from .research_agent import ResearchAgent
from .retry_managers import DBRetryManager, LLMRetryManager, StageRetryManager, retry_async
from .synthesizer import ResearchSynthesizer
from .source_filter import SourceFilter
from .state import VALID_TRANSITIONS, ActionMetrics, ResearchState, SessionMetrics
from .structure_validator import StructureValidator

__all__ = [
    # Engine
    "ResearchEngine",
    "ResearchAgent",
    "ReportGenerator",
    "ResearchSynthesizer",
    "DEFAULT_SIX_STEP_CONFIG",
    "merge_six_step_config",
    "GateResult",
    "QualityGate",
    "ReasoningChecker",
    "DBRetryManager",
    "LLMRetryManager",
    "StageRetryManager",
    "retry_async",
    "ResearchClarifier",
    "ResearchState",
    "SourceFilter",
    "StructureValidator",
    "ResearchGates",
    "VALID_TRANSITIONS",
    "LLMCallMetrics",
    "MetricsCollector",
    "ActionMetrics",
    "SessionMetrics",
    # C1: new chat framework
    "ChatBase",
    "ChatMessage",
    "ChatSession",
    "Harness",
    "GoldenCase",
    "CaseResult",
    "HarnessReport",
    # v0.32 Phase 3: unified DB
    "ChatDatabase",
    "AutoResearchDatabase",  # back-compat alias
]
