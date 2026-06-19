"""Research engine subpackage — v0.41 6-step framework, inlined.

In 2026-06-19, all 9 modules from
``archive/llmwikify_v0_41_legacy/chat_legacy/`` were git-mv'd here
so production code (clarifier, research_agent, harness/review) and
test code could drop their archive imports and resolve cleanly.

Modules:
    actions        — 8 action functions + ActionContext
    engine         — ResearchEngine (ReAct loop orchestrator)
    gates          — ResearchGates (framework & quality compliance)
    llm_step       — run_prompt (unified LLM call layer)
    observer       — ResearchObserver (state refresh)
    reasoner       — ResearchReasoner (ReAct Thought step)
    report         — ReportGenerator
    resume         — ResearchResumeLoader
    routes         — legacy /api/autoresearch/* FastAPI router

Back-compat: ``llmwikify.apps.chat.__init__`` re-exports the public
API (ResearchEngine, run_prompt, ReportGenerator, ResearchGates, ...)
and registers submodules in sys.modules so legacy import paths like
``llmwikify.apps.chat.engine`` still work.
"""
from .actions import ActionContext
from .engine import ResearchEngine
from .gates import ResearchGates
from .llm_step import LLMCallMetrics, run_prompt
from .observer import ResearchObserver
from .reasoner import VALID_ACTIONS, ResearchReasoner
from .report import ReportGenerator
from .resume import ResearchResumeLoader

__all__ = [
    "ActionContext",
    "LLMCallMetrics",
    "ReportGenerator",
    "ResearchEngine",
    "ResearchGates",
    "ResearchObserver",
    "ResearchReasoner",
    "ResearchResumeLoader",
    "VALID_ACTIONS",
    "run_prompt",
]
