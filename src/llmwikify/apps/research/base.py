"""Base classes shared by ``apps/research/`` and ``apps/chat/``.

Sprint C4 of the 4-layer refactor (design doc
``docs/designs/refactor-4layer-architecture.md``) consolidates
the duplicated code that used to live in both packages. The
canonical home is ``apps/research/base.py`` because:

- ``apps/chat/`` is allowed to import from ``apps/research/``
  (the only allowed L3→L3 direction, per design decision D7).
- Putting the base class in either L3 package would create a
  circular import (each package wanting to import the base
  from the other). ``apps/research/`` is the natural anchor
  because ``apps/chat/`` already imports helpers from it
  (e.g. ``apps.research.web_search``).

This file currently hosts ``BaseResearchConfig``. Future
batches (Step 2-4 of C4) will add ``BaseQualityGate``,
``BaseResearchTaskManager``, and ``BaseReportGenerator``
alongside it.

Backward compatibility
-----------------------
Every public symbol exposed by the base class is also
re-exported from the per-package module (e.g.
``apps.research.config.DEFAULT_RESEARCH_CONFIG``). External
callers, the 14 ``agent/backend/research.*.py`` shim files,
and ``_legacy/autoresearch.py`` all continue to work without
any import-path change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class BaseResearchConfig:
    """Shared default config keys + merge helper for both packages.

    The 31 keys defined here were duplicated verbatim between
    ``apps/research/config.py::DEFAULT_RESEARCH_CONFIG`` and
    ``apps/chat/config.py::DEFAULT_SIX_STEP_CONFIG``. The chat
    side has 30+ additional keys for the 6-step framework
    (clarify, evidence, structure, etc.); see
    ``apps/chat/config.py::_SIX_STEP_EXTRAS``.

    Subclasses and consumers must treat ``DEFAULT`` as
    read-only. Use :meth:`merge` (or the per-package
    ``merge_*_config`` thin wrappers) to produce a runtime
    config dict.
    """

    DEFAULT: dict[str, Any] = {
        "max_sub_queries": 20,
        "max_source_content_length": 500000,
        "research_timeout_minutes": 30,
        "max_parallel_gathering": 5,
        "web_search_results_per_query": 5,
        "max_retry_attempts": 3,
        "similarity_threshold": 0.92,
        "max_review_rounds": 2,
        "planning_model": None,
        "report_model": None,
        "llm_call_timeout_seconds": 120,
        # Search provider config
        "search_provider": "auto",       # "auto", "searxng", "minimax", "tavily", "duckduckgo"
        "searxng_url": None,             # e.g. "http://localhost:8888"
        "minimax_api_key": None,         # MiniMax Token Plan API key
        "minimax_api_host": "https://api.minimaxi.com",  # domestic endpoint
        "tavily_api_key": None,          # e.g. "tvly-xxxxx"
        # ReAct config
        "max_react_rounds": 10,          # Max ReAct loop iterations
        "quality_threshold": 7,          # Score >= 7 is approved
        "max_replan_attempts": 2,        # Max replanning for knowledge gaps
        "parallel_wiki_search": True,    # Search local wiki alongside web results
        # Source filter config
        "source_filter_enabled": True,   # Enable rule-based source pre-filter
        "source_min_content_length": 100,  # Min content length to keep
        "source_min_quality_score": 0.3,   # Min quality score to keep
        # Report content budget
        "report_max_per_source": 4000,     # Max chars per source in report prompt
        "report_max_total_content": 60000, # Max total source chars in report prompt
        # Quality gate config (base 4 gates)
        "gate_enabled": True,            # Enable quality gates
        "gate_min_sources": 3,           # Min sources after gathering
        "gate_min_type_diversity": 2,    # Min source type diversity
        "gate_min_analyzed": 2,          # Min analyzed sources
        "gate_min_avg_credibility": 5,   # Min avg credibility after analysis
        "gate_max_knowledge_gaps": 3,    # Max knowledge gaps after synthesis
        "gate_min_reinforced_claims": 2, # Min reinforced claims after synthesis
    }

    @classmethod
    def merge(cls, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a fresh copy of :attr:`DEFAULT` with overrides applied.

        Override keys that are not present in ``DEFAULT`` are
        silently ignored (this matches the v0.30.1 behavior of
        both packages' ``merge_*_config`` helpers — see
        ``test_merge_ignores_unknown_keys``).
        """
        config = dict(cls.DEFAULT)
        if overrides:
            for k, v in overrides.items():
                if k in config and v is not None:
                    config[k] = v
        return config

