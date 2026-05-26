"""Deep Research configuration."""

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
}


def merge_research_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_RESEARCH_CONFIG)
    if overrides:
        for k, v in overrides.items():
            if k in config and v is not None:
                config[k] = v
    return config
