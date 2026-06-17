"""Stage 1 Call 2: paper planner.

Decides:
- schema_choice (factor / signal / allocation / summary)
- paper_type (free-text label)
- n_signals_estimate
- extraction_strategy
- token_budget (per-stage max_tokens allocation)
- confidence (triggers re-plan if < 0.6)

Inputs: full paper text + sections from Call 1 (optional).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

from .llm_factory import build_default_client
from .retry import DeferError, RetryConfig, with_retry
from .section_detector import Section

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)


@with_retry(stage="stage1_call2", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_llm_with_retry(client: Any, messages: list, **api_params: Any) -> str:
    """Thin wrapper around ``client.chat`` with L1 retry."""
    return client.chat(messages, **api_params)

PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "foundation"
    / "prompts"
    / "_defaults"
    / "repro_extract_plan.yaml"
)

API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}

VALID_SCHEMAS = {"factor", "signal", "allocation", "summary"}

DEFAULT_TOKEN_BUDGET = {
    "track_a_tier1": 4500,
    "track_a_tier2_per_section": 3000,
    "track_b_pass1": 3500,
    "track_b_pass2_per_factor": 5500,
    "preview": 2000,
}

# Lower bounds (safety floor) — must not go below these to avoid truncation.
# Upper bound: no hard cap here; the model context window (1M for M2.7) is
# the absolute ceiling. Stage 1 LLM is free to allocate more if the content
# demands it (e.g. 101 Alphas per-factor detail).
TOKEN_BUDGET_FLOOR = {
    "track_a_tier1": 3072,
    "track_a_tier2_per_section": 2048,
    "track_b_pass1": 12000,  # Support 200+ alpha papers (name+formula only)
    "track_b_pass2_per_factor": 4096,
    "preview": 1536,
}


@dataclass
class PlanResult:
    paper_id: str
    schema_choice: str = "summary"
    paper_type: str = ""
    n_signals_estimate: int = 0
    extraction_strategy: str = ""
    token_budget: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw_response: str = ""
    latency_ms: int = 0
    success: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _load_prompt() -> tuple[str, str, dict[str, Any]]:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt not found: {PROMPT_PATH}")
    import yaml
    raw = yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))
    return raw.get("system", ""), raw.get("user", ""), raw.get("params", {})


def _extract_json(text: str) -> dict | None:
    """Extract and parse JSON, with simple bracket-closing repair."""
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
        in_str = False
        esc = False
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


def _clamp_token_budget(budget: dict) -> dict:
    """Clamp each field to its configured floor (min). No upper cap.

    Safety: enforce minimum so we don't truncate critical content.
    Flexibility: allow LLM to allocate more (e.g. 101 Alphas per-factor).
    Hard ceiling = model context window (M2.7: 1M tokens).
    """
    clamped: dict = {}
    for key, value in budget.items():
        if not isinstance(value, (int, float)):
            continue
        floor = TOKEN_BUDGET_FLOOR.get(key)
        if floor is not None:
            clamped[key] = max(floor, int(value))
        else:
            clamped[key] = int(value)
    return clamped


def plan_paper(
    paper_id: str,
    title: str,
    parsed_text: str,
    sections: list[Section] | None = None,
    llm_client: Any | None = None,
) -> PlanResult:
    """Run Stage 1 Call 2: classify + plan + token_budget.

    Args:
        paper_id: Stable paper identifier.
        title: Paper title (from Stage 0 or filename).
        parsed_text: Full text from Stage 0.
        sections: Optional sections from Call 1 (improves planning accuracy).
        llm_client: Optional pre-built LLM client.

    Returns:
        PlanResult with all planning fields populated. ``success=False``
        indicates parse failure; caller should treat as "fallback plan"
        or re-plan.
    """
    system_text, user_template, params = _load_prompt()
    client = llm_client or build_default_client()

    section_dicts = [s.to_dict() for s in (sections or [])]
    tmpl = _jinja_env.from_string(user_template)
    user_msg = tmpl.render(
        paper_id=paper_id,
        title=title,
        char_count=len(parsed_text),
        n_sections=len(section_dicts),
        sections=section_dicts,
        paper_text=parsed_text,
    )

    api_params = {k: v for k, v in params.items() if k in API_PARAM_KEYS}
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_msg},
    ]

    logger.info(
        "[planner] paper=%s sections=%d text_len=%d",
        paper_id, len(section_dicts), len(parsed_text),
    )
    import time
    t0 = time.monotonic()
    try:
        response = _call_llm_with_retry(client, messages, **api_params)
    except DeferError:
        raise
    except Exception as exc:
        logger.warning("[planner] paper=%s LLM call failed: %s", paper_id, exc)
        return PlanResult(paper_id=paper_id, success=False, error=f"llm_error: {exc}")
    latency_ms = int((time.monotonic() - t0) * 1000)

    data = _extract_json(response)
    if not data:
        return PlanResult(
            paper_id=paper_id, raw_response=response[:1000],
            latency_ms=latency_ms, success=False, error="json_parse_failed",
        )

    schema = str(data.get("schema_choice", "summary")).lower().strip()
    if schema not in VALID_SCHEMAS:
        schema = "summary"

    n_signals = max(0, int(data.get("n_signals_estimate", 0) or 0))
    confidence = float(data.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    raw_budget = data.get("token_budget", {}) or {}
    token_budget = _clamp_token_budget(raw_budget)
    # Always ensure all keys present
    for key, default in DEFAULT_TOKEN_BUDGET.items():
        token_budget.setdefault(key, default)

    logger.info(
        "[planner] paper=%s plan: schema=%s n_signals=%d conf=%.2f (%dms)",
        paper_id, schema, n_signals, confidence, latency_ms,
    )
    return PlanResult(
        paper_id=paper_id,
        schema_choice=schema,
        paper_type=str(data.get("paper_type", "")).strip(),
        n_signals_estimate=n_signals,
        extraction_strategy=str(data.get("extraction_strategy", "")).strip(),
        token_budget=token_budget,
        confidence=confidence,
        raw_response=response[:1000],
        latency_ms=latency_ms,
        success=True,
    )
