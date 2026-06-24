"""Track A: Paper/Strategy-level extraction (Tier 1 + Tier 2).

Calls schema-specific prompt for Tier 1, then 5 Tier 2 detail prompts.
Each Tier 2 section has its own prompt and max_tokens budget.

Schemas: factor | signal | allocation | summary
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

from ..common.llm_factory import build_default_client
from .planner import PlanResult
from .retry import DeferError, RetryConfig, with_retry
from .section_detector import Section

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)

PROMPTS_DIR = (
    Path(__file__).parent.parent.parent
    / "foundation"
    / "prompts"
    / "_defaults"
)

SCHEMA_PROMPTS = {
    "factor": "repro_extract_factor.yaml",
    "signal": "repro_extract_signal.yaml",
    "allocation": "repro_extract_allocation.yaml",
    "summary": "repro_extract_summary.yaml",
}

TIER2_PROMPTS = [
    "repro_extract_tier2_backtest.yaml",
    "repro_extract_tier2_performance.yaml",
    "repro_extract_tier2_risk.yaml",
    "repro_extract_tier2_implementation.yaml",
    "repro_extract_tier2_datasets.yaml",
]

API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}


@dataclass
class TrackAResult:
    paper_id: str
    schema_choice: str = "summary"
    tier1: dict = field(default_factory=dict)
    tier2: dict = field(default_factory=dict)
    tier2_sections_attempted: list = field(default_factory=list)
    tier2_sections_failed: list = field(default_factory=list)
    success: bool = False
    error: str | None = None
    latency_ms_total: int = 0
    latency_ms_tier1: int = 0
    latency_ms_tier2: int = 0
    llm_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _load_prompt(prompt_file: str) -> tuple[str, str, dict[str, Any]]:
    path = PROMPTS_DIR / prompt_file
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw.get("system", ""), raw.get("user", ""), raw.get("params", {})


def _extract_json(text: str) -> dict | None:
    """Extract and parse JSON, with bracket-closing repair on truncation."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        candidate = match.group()
        opens_b, opens_s = 0, 0
        in_str, esc = False, False
        for ch in candidate:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "{":
                    opens_b += 1
                elif ch == "}":
                    opens_b -= 1
                elif ch == "[":
                    opens_s += 1
                elif ch == "]":
                    opens_s -= 1
        if opens_b > 0 or opens_s > 0:
            candidate = candidate.rstrip(",\n ") + "]" * opens_s + "}" * opens_b
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


@with_retry(stage="track_a", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_chat(client: Any, messages: list, max_tokens: int, temperature: float) -> str:
    """Thin wrapper around ``client.chat`` with L1 retry."""
    return client.chat(messages, max_tokens=max_tokens, temperature=temperature)


def _call_llm(
    client: Any,
    system_text: str,
    user_msg: str,
    max_tokens: int,
    temperature: float = 0.1,
) -> tuple[str, int]:
    """Call LLM and return (response, latency_ms)."""
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_msg},
    ]
    t0 = time.monotonic()
    response = _call_chat(client, messages, max_tokens, temperature)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return response, latency_ms


def _run_tier1(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    title: str,
    parsed_text: str,
    sections: list[Section] | None,
) -> tuple[dict, int]:
    """Run Track A Tier 1: 8 core paper-level sections.

    Returns (parsed_dict, latency_ms).
    """
    schema = plan.schema_choice
    if schema not in SCHEMA_PROMPTS:
        raise ValueError(f"Unknown schema: {schema}")
    prompt_file = SCHEMA_PROMPTS[schema]
    system_text, user_template, params = _load_prompt(prompt_file)

    section_dicts = [s.to_dict() for s in (sections or [])]
    tmpl = _jinja_env.from_string(user_template)
    user_msg = tmpl.render(
        paper_id=paper_id,
        title=title,
        n_sections=len(section_dicts),
        sections=section_dicts,
        paper_text=parsed_text,
    )

    # Use planner's budget; fall back to prompt's default
    default_max = int(params.get("max_tokens", 6144))
    budget_max = int(plan.token_budget.get("track_a_tier1", default_max))
    max_tokens = max(default_max, budget_max)

    response, latency_ms = _call_llm(
        client, system_text, user_msg, max_tokens=max_tokens,
    )
    parsed = _extract_json(response)
    if not parsed:
        logger.warning(
            "[track_a] tier1 paper=%s JSON parse failed (response %d chars)",
            paper_id, len(response),
        )
        return {}, latency_ms
    logger.info(
        "[track_a] tier1 paper=%s ok (%d fields, %dms)",
        paper_id, len(parsed), latency_ms,
    )
    return parsed, latency_ms


def _run_tier2(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    parsed_text: str,
) -> tuple[dict, list, list, int]:
    """Run Track A Tier 2: 5 detail sections in sequence.

    Returns (tier2_dict, attempted, failed, latency_ms).
    """
    tier2: dict = {}
    attempted: list = []
    failed: list = []
    total_latency = 0

    default_max = 4096
    budget_max = int(
        plan.token_budget.get("track_a_tier2_per_section", default_max)
    )
    max_tokens = max(default_max, budget_max)

    logger.info(
        "[track_a] paper=%s tier2: %d sections starting (max_tokens=%d)",
        paper_id, len(TIER2_PROMPTS), max_tokens,
    )
    for i, prompt_file in enumerate(TIER2_PROMPTS, 1):
        section_name = prompt_file.replace("repro_extract_tier2_", "").replace(".yaml", "")
        attempted.append(section_name)
        logger.info(
            "[track_a] paper=%s tier2 [%d/%d] %s: running",
            paper_id, i, len(TIER2_PROMPTS), section_name,
        )
        try:
            system_text, user_template, params = _load_prompt(prompt_file)
            tmpl = _jinja_env.from_string(user_template)
            user_msg = tmpl.render(paper_id=paper_id, paper_text=parsed_text)
            response, latency = _call_llm(
                client, system_text, user_msg, max_tokens=max_tokens,
            )
            total_latency += latency
            parsed = _extract_json(response)
            if parsed:
                # Each Tier 2 prompt returns one top-level key (e.g. backtest_spec)
                if len(parsed) == 1:
                    key = next(iter(parsed))
                    tier2[key] = parsed[key]
                else:
                    # Multiple keys (e.g. risk_analysis may wrap sub-keys)
                    tier2.update(parsed)
                logger.info(
                    "[track_a] tier2 %s paper=%s ok (%dms)",
                    section_name, paper_id, latency,
                )
            else:
                failed.append(section_name)
                logger.warning(
                    "[track_a] tier2 %s paper=%s JSON parse failed",
                    section_name, paper_id,
                )
        except DeferError:
            raise
        except Exception as exc:
            failed.append(section_name)
            logger.warning(
                "[track_a] tier2 %s paper=%s error: %s",
                section_name, paper_id, exc,
            )
    return tier2, attempted, failed, total_latency


def run_track_a(
    paper_id: str,
    title: str,
    parsed_text: str,
    plan: PlanResult,
    sections: list[Section] | None = None,
    llm_client: Any | None = None,
    run_tier2: bool = True,
) -> TrackAResult:
    """Run Track A: paper-level extraction (Tier 1 + optional Tier 2).

    Args:
        paper_id: Stable paper identifier.
        title: Paper title.
        parsed_text: Full text from Stage 0.
        plan: Stage 1 Call 2 plan (schema_choice + token_budget).
        sections: Optional sections from Stage 1 Call 1.
        llm_client: Optional pre-built LLM client.
        run_tier2: Whether to also run the 5 Tier 2 detail sections.

    Returns:
        TrackAResult with tier1 dict + tier2 dict + stats.
    """
    client = llm_client or build_default_client()

    t_total = time.monotonic()
    # Tier 1
    tier1, t1_latency = _run_tier1(
        client, plan, paper_id, title, parsed_text, sections,
    )

    if not tier1:
        return TrackAResult(
            paper_id=paper_id,
            schema_choice=plan.schema_choice,
            tier1={},
            success=False,
            error="tier1_failed",
            latency_ms_tier1=t1_latency,
            latency_ms_total=int((time.monotonic() - t_total) * 1000),
            llm_calls=1,
        )

    # Tier 2 (optional)
    tier2: dict = {}
    attempted: list = []
    failed: list = []
    t2_latency = 0
    if run_tier2:
        tier2, attempted, failed, t2_latency = _run_tier2(
            client, plan, paper_id, parsed_text,
        )

    total = int((time.monotonic() - t_total) * 1000)
    n_calls = 1 + len(attempted)

    return TrackAResult(
        paper_id=paper_id,
        schema_choice=plan.schema_choice,
        tier1=tier1,
        tier2=tier2,
        tier2_sections_attempted=attempted,
        tier2_sections_failed=failed,
        success=True,
        latency_ms_total=total,
        latency_ms_tier1=t1_latency,
        latency_ms_tier2=t2_latency,
        llm_calls=n_calls,
    )
