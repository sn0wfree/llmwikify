"""Quick Research configuration."""

from __future__ import annotations

from typing import Any

DEFAULT_RESEARCH_CONFIG: dict[str, Any] = {
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
    "minimax_api_host": "https://api.minimaxi.com",  # 国内版
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
    # Quality gate config
    "gate_enabled": True,            # Enable quality gates
    "gate_min_sources": 3,           # Min sources after gathering
    "gate_min_type_diversity": 2,    # Min source type diversity
    "gate_min_analyzed": 2,          # Min analyzed sources
    "gate_min_avg_credibility": 5,   # Min avg credibility after analysis
    "gate_max_knowledge_gaps": 3,    # Max knowledge gaps after synthesis
    "gate_min_reinforced_claims": 2, # Min reinforced claims after synthesis
}


def merge_research_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_RESEARCH_CONFIG)
    if overrides:
        for k, v in overrides.items():
            if k in config and v is not None:
                config[k] = v
    return config
