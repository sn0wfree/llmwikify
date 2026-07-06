"""L3 apps/chat/ — generic chat framework + research agent.

This package is the L3 home for the chat subsystem, organized around
three pillars:

- **ResearchAgent** (``research_agent.py``) — thin ChatBase wrapper
  around the 6-step research engine (``apps.research.engine``). It
  exposes a chat-style API (``await agent.aresearch(query)``) and
  preserves the legacy sync ``.research()`` signature.
- **ChatBase** (``base.py``) — generic chat framework: session and
  message management, streaming output, tool registration, LLM
  provider abstraction. Designed for reuse across chat-driven apps.
- **Harness** (``eval_harness.py`` + ``harness/`` subpackage) — eval
  framework: golden test cases, LLM-as-judge scoring, regression
  detection, ``@pytest.mark.harness`` integration.

Layout (post v0.40)
-------------------

    apps/chat/
    ├── base.py                    (1.5K LOC) — ChatBase
    ├── research_agent.py          (142 LOC)  — ResearchAgent(ChatBase)
    ├── eval_harness.py            — Harness, GoldenCase, CaseResult, HarnessReport
    ├── harness/                   (subpackage) — quality_gate, source_filter,
    │                                              structure_validator, review,
    │                                              source_analyzer, service
    ├── agent/                     (30 files) — ReAct orchestrator, runner v2,
    │                                            microcompact, subagent manager,
    │                                            prompt builder, etc. (see
    │                                            apps/chat/agent/orchestrator.py:
    │                                            37K LOC)
    ├── db/                        — unified chat database (Phase v0.32)
    ├── providers/                 — LLM provider registry (factory, base, abc)
    ├── skills/                    — skill plugins + workflow DSL + 7 actor prompts
    ├── bus/                       — pub/sub bus adapters
    ├── channels/                  — channel adapters (cli, http, mcp)
    ├── memory/                    — long-term memory
    ├── config.py / config_manager.py / state.py / etc.  — config + state
    ├── command_router.py          — slash command dispatch (priority / exact / prefix)
    ├── README.md                  — package-level design doc

For the **6-step research engine** (the heavy lifter behind
ResearchAgent), see ``apps/research/`` (Phase 4 canonical home).
Legacy import path ``apps.chat.research_engine.*`` is preserved as
a thin PEP 562 / back-compat shim that re-exports from
``apps.research.*``.

For **L1 primitives** (LLM client, prompt registry, callback hooks),
see ``llmwikify.foundation.*``.

For **L2 domain abstractions** (wiki engine, knowledge graph, search,
storage, multi-wiki), see ``llmwikify.kernel.*``.
"""
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
            value = mod.router
            globals()[name] = value
            return value
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r} "
            f"(looked in {mod_path})"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Import-time constants for the public surface. Placed after the
# PEP 562 __getattr__ so that the latter's lazy-resolve path stays
# intact at module-load time.
from .retry_managers import (  # noqa: E402
    DBRetryManager,
    LLMRetryManager,
    StageRetryManager,
    retry_async,
)
from .state import (  # noqa: E402
    VALID_TRANSITIONS,
    ActionMetrics,
    MetricsCollector,
    ResearchState,
    SessionMetrics,
)
from .synthesizer import ResearchSynthesizer  # noqa: E402

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
