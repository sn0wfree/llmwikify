"""AutoResearch independent configuration.

Defines the 6-step framework configuration, self-loop settings, and
retry parameters. Does not depend on agent.backend.research.config.
"""

from __future__ import annotations

from typing import Any

DEFAULT_SIX_STEP_CONFIG: dict[str, Any] = {
    # ─── Reuse base research config (DRY: start with the same defaults) ──
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
    "search_provider": "auto",
    "searxng_url": None,
    "minimax_api_key": None,
    "minimax_api_host": "https://api.minimaxi.com",
    "tavily_api_key": None,
    # ReAct config
    "max_react_rounds": 10,
    "quality_threshold": 7,
    "max_replan_attempts": 2,
    "parallel_wiki_search": True,
    # Source filter config
    "source_filter_enabled": True,
    "source_min_content_length": 100,
    "source_min_quality_score": 0.3,
    # Report content budget
    "report_max_per_source": 4000,
    "report_max_total_content": 60000,
    # Quality gate config (base 4 gates)
    "gate_enabled": True,
    "gate_min_sources": 3,
    "gate_min_type_diversity": 2,
    "gate_min_analyzed": 2,
    "gate_min_avg_credibility": 5,
    "gate_max_knowledge_gaps": 3,
    "gate_min_reinforced_claims": 2,

    # ─── 6-step framework switches (no off-switch for self-loop) ───
    "clarify_enabled": True,
    "reasoning_check_enabled": True,
    "structure_check_enabled": True,
    "evidence_scoring_enabled": True,
    "framework_check_enabled": True,

    # ─── 6-step gate thresholds ───
    "gate_min_evidence_score": 0.5,
    "gate_min_traceable_sources": 2,
    "gate_min_reasoning_score": 7,
    "gate_max_reasoning_issues": 3,
    "gate_min_structure_score": 7,
    "gate_min_source_refs": 3,

    # ─── Self-loop (must be enabled, no off-switch) ───
    "clarify_max_retries": 2,
    "evidence_max_retries": 2,
    "self_loop_budget_ratio": 0.3,

    # ─── Retry managers (3 independent) ───
    "stage_max_retries": 2,
    "stage_retry_base_delay": 2.0,
    "llm_parse_max_retries": 3,
    "db_retry_base_delay": 1.0,
    "db_retry_max_retries": 3,
}


def merge_six_step_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge user overrides on top of the 6-step defaults.

    Unlike research.config, the self-loop and framework check switches
    are kept on (no off path) per the v3 design decision.
    """
    config = dict(DEFAULT_SIX_STEP_CONFIG)
    if overrides:
        for k, v in overrides.items():
            if k in config and v is not None:
                config[k] = v
    return config


# Backward-compat alias; the engine and tests still reference the old name.
merge_research_config = merge_six_step_config
