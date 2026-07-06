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

# v0.40: research_engine 已被合并到 apps.research/ 主包. chat.research_engine/
# 留作 thin wrapper (back-compat). 旧 import 仍工作 (`from llmwikify.apps.chat
# import ResearchEngine`) 但走 apps.research 路径以避免循环 import.
#
# IMPORTANT: use PEP 562 lazy attribute access (via __getattr__) — eager
# imports would create cycles: research.engine imports chat.config which
# imports this __init__, and research.engine is mid-loading.

_LAZY_ATTRS = {
    "ResearchEngine": "llmwikify.apps.research.engine",
    "ResearchDatabase": "llmwikify.apps.research.db",
    "WebSearch": "llmwikify.apps.research.web_search",
    "research_router": "llmwikify.apps.research.routes",
    "ResearchGates": "llmwikify.apps.research.gates",
    "LLMCallMetrics": "llmwikify.apps.research.llm_step",
    "ReportGenerator": "llmwikify.apps.research.report",
}


def __getattr__(name: str):
    if name in _LAZY_ATTRS:
        from importlib import import_module

        mod_path = _LAZY_ATTRS[name]
        # Resolve the submodule and look up the symbol.
        mod = import_module(mod_path)
        if hasattr(mod, name):
            value = getattr(mod, name)
            globals()[name] = value
            return value
        # Special handling: research_router is exported as ``router`` from
        # the routes submodule, but the legacy chat-__init__ callers expect
        # the attribute ``research_router``.
        if name == "research_router" and hasattr(mod, "router"):
            value = getattr(mod, "router")
            globals()[name] = value
            return value
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r} "
            f"(looked in {mod_path})"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
