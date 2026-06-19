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
import sys as _sys

from .base import ChatBase, ChatMessage, ChatSession
from .clarifier import ResearchClarifier
from .config import DEFAULT_SIX_STEP_CONFIG, merge_six_step_config
from .db import AutoResearchDatabase, ChatDatabase
from .eval_harness import CaseResult, GoldenCase, Harness, HarnessReport
from .harness.quality_gate import GateResult, QualityGate
from .harness.source_filter import SourceFilter
from .harness.structure_validator import StructureValidator
from .reasoning_checker import ReasoningChecker
from .research_agent import ResearchAgent

# Back-compat re-exports: v0.41 modules moved from archive/ to
# apps/chat/research_engine/ in 2026-06-19. The classes themselves
# are unchanged; only the import path changed. Re-exported here so
# existing callers (``from llmwikify.apps.chat import ResearchEngine``
# or ``import llmwikify.apps.chat.engine``) still work.
from .research_engine import (  # noqa: F401
    ResearchEngine,  # noqa: F401
    actions,  # noqa: F401
    engine,  # noqa: F401
    gates,  # noqa: F401
    llm_step,  # noqa: F401
    observer,  # noqa: F401
    reasoner,  # noqa: F401
    report,  # noqa: F401
    resume,  # noqa: F401
    routes,  # noqa: F401
)
from .research_engine.gates import (  # noqa: F401
    ResearchGates,
)
from .research_engine.llm_step import (  # noqa: F401
    LLMCallMetrics,
)
from .research_engine.report import (  # noqa: F401
    ReportGenerator,
)
from .retry_managers import (
    DBRetryManager,
    LLMRetryManager,
    StageRetryManager,
    retry_async,
)
from .state import (
    VALID_TRANSITIONS,
    ActionMetrics,
    MetricsCollector,
    ResearchState,
    SessionMetrics,
)
from .synthesizer import ResearchSynthesizer

# Register research_engine submodules in sys.modules so that legacy
# direct-submodule imports (``import llmwikify.apps.chat.engine``)
# still resolve to the new location.
for _name in (
    "actions", "engine", "observer", "gates", "reasoner", "report",
    "llm_step", "resume", "routes",
):
    _sys.modules.setdefault(
        f"llmwikify.apps.chat.{_name}",
        _sys.modules[f"llmwikify.apps.chat.research_engine.{_name}"],
    )

__all__ = [
    # Engine
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
