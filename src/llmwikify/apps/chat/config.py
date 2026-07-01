"""AutoResearch independent configuration.

Defines the 6-step framework configuration, self-loop settings,
and retry parameters.

Per Sprint C4 of the 4-layer refactor, the 31 keys shared with
``apps/research/config.py`` now live in
:mod:`llmwikify.apps.research.base.BaseResearchConfig`. The
30+ keys specific to the 6-step framework (clarify / evidence /
structure / strict-exit / retry managers / per-prompt
``llm_params``) are kept in this module as ``_SIX_STEP_EXTRAS``
and merged with the base defaults at module load.
"""

from __future__ import annotations

from typing import Any

from llmwikify.apps.research.base import BaseResearchConfig

_SIX_STEP_EXTRAS: dict[str, Any] = {
    # ─── 6-step framework switches (no off-switch for self-loop) ───
    "clarify_enabled": True,
    "reasoning_check_enabled": True,
    "structure_check_enabled": True,
    "evidence_scoring_enabled": True,
    "framework_check_enabled": True,

    # ─── Strict exit gate (v6) ───
    # When True (default), the done gate also enforces quality thresholds:
    # review approved, quality_score >= quality_threshold, knowledge_gaps
    # <= gate_max_knowledge_gaps, sources >= gate_min_sources. If any
    # check fails, the engine redirects to the missing action (revise /
    # synthesize / gather) instead of marking done. Disable for legacy
    # behavior where any session with all 6 framework steps can be done.
    "strict_exit": True,

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

    # ─── Chat service parameters (v0.38) ───
    "max_chat_rounds": 4,
    "max_messages": 50,
    "observation_limit": 10,
    "observation_summary_limit": 5,
    "summary_truncate_chars": 500,
    "content_truncate_chars": 10_000,

    # ─── Context store limits (v0.39 P0-1) ───
    "context_store_max_size": 200,
    "context_store_ttl_seconds": 1800,  # 30 minutes

    # ─── Token-aware truncation (v0.39 P0-2) ───
    "context_reserve_tokens": 4096,  # reserve for LLM output
    "context_window_override": 0,    # 0 = use model's actual context window

    # ─── Message compaction (v0.39 P1-1) ───
    "compaction_enabled": True,
    "compaction_threshold_ratio": 0.8,  # trigger at 80% of budget
    "compaction_min_messages": 6,        # need at least 6 messages to compact
    "compaction_max_tokens": 4000,       # max tokens to summarize at once
    "llm_retry_max_attempts": 3,
    "llm_retry_base_delay": 2.0,
    "llm_retry_call_timeout": 120.0,
    "llm_retry_max_delay": 30.0,
    "chat_db_retry_max_attempts": 3,
    "chat_db_retry_base_delay": 0.2,

    # ─── LLM call params per prompt (overridable, fed to resolve_llm_params) ───
    # Each section is a per-prompt dict. Priority chain:
    #   1. this config → 2. prompt YAML → 3. DEFAULT_LLM_PARAMS safety net.
    "llm_params": {
        "research_plan":   {"max_tokens": 2048, "temperature": 0.3, "json_mode": True},
        "research_replan": {"max_tokens": 1024, "temperature": 0.3, "json_mode": True},
        "research_clarify":{"max_tokens": 4096, "temperature": 0.3, "json_mode": True},
        "research_reason": {"max_tokens": 1024, "temperature": 0.1, "json_mode": True},
        "research_report": {"max_tokens": 8192, "temperature": 0.3, "json_mode": False},
        "research_review": {"max_tokens": 2048, "temperature": 0.1, "json_mode": True},
        "research_revise": {"max_tokens": 8192, "temperature": 0.3, "json_mode": False},
    },
}


DEFAULT_SIX_STEP_CONFIG: dict[str, Any] = {
    **BaseResearchConfig.DEFAULT,
    **_SIX_STEP_EXTRAS,
}


def merge_six_step_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge user overrides on top of the 6-step defaults.

    Unlike ``merge_research_config``, the self-loop and
    framework check switches are kept on (no off path) per the
    v3 design decision.
    """
    config = dict(DEFAULT_SIX_STEP_CONFIG)
    if overrides:
        for k, v in overrides.items():
            if k in config and v is not None:
                config[k] = v
    return config


# Backward-compat alias; the engine and tests still reference the old name.
merge_research_config = merge_six_step_config
