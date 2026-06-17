"""Track B: Factor-level extraction (Pass 1 enumerate + Pass 2 detail).

Pass 1: enumerate all signals (name + brief formula) in one LLM call.
Pass 2: for each signal, extract L1-L4 in 3-way concurrent LLM calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

from .llm_factory import build_default_client
from .planner import PlanResult
from .retry import DeferError, RetryConfig, with_retry
from .section_detector import Section

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)

PROMPT_PASS1 = "repro_extract_track_b_pass1.yaml"
PROMPT_PASS2 = "repro_extract_track_b_pass2.yaml"

API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}


@with_retry(stage="track_b_pass1", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_chat_pass1(client: Any, messages: list, max_tokens: int) -> str:
    """Pass 1 chat with L1 retry."""
    return client.chat(messages, max_tokens=max_tokens, temperature=0.1)


@with_retry(stage="track_b_pass2", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_chat_pass2(client: Any, messages: list, max_tokens: int) -> str:
    """Pass 2 per-factor chat with L1 retry."""
    return client.chat(messages, max_tokens=max_tokens, temperature=0.1)

BATCH_SIZE = 10
BATCH_MAX_TOKENS = 5000
MAX_BATCHES = 30


@dataclass
class SignalStub:
    """Pass 1 output: brief signal enumeration."""
    index: int
    name: str
    formula_brief: str
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SignalDetail:
    """Pass 2 output: full L1-L4 factor metadata."""
    name: str
    description: str = ""
    l1: dict = field(default_factory=dict)
    l2: dict = field(default_factory=dict)
    l3: dict = field(default_factory=dict)
    l4: dict = field(default_factory=dict)
    success: bool = False
    error: str | None = None
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrackBResult:
    paper_id: str
    schema_choice: str = "summary"
    enabled: bool = False
    pass1_signals: list[SignalStub] = field(default_factory=list)
    pass2_details: list[SignalDetail] = field(default_factory=list)
    n_pass1: int = 0
    n_pass2_complete: int = 0
    n_pass2_failed: int = 0
    pass1_latency_ms: int = 0
    pass2_latency_ms: int = 0
    pass2_concurrency: int = 3
    total_latency_ms: int = 0
    llm_calls: int = 0
    success: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "schema_choice": self.schema_choice,
            "enabled": self.enabled,
            "pass1_signals": [s.to_dict() for s in self.pass1_signals],
            "pass2_details": [d.to_dict() for d in self.pass2_details],
            "n_pass1": self.n_pass1,
            "n_pass2_complete": self.n_pass2_complete,
            "n_pass2_failed": self.n_pass2_failed,
            "pass1_latency_ms": self.pass1_latency_ms,
            "pass2_latency_ms": self.pass2_latency_ms,
            "pass2_concurrency": self.pass2_concurrency,
            "total_latency_ms": self.total_latency_ms,
            "llm_calls": self.llm_calls,
            "success": self.success,
            "error": self.error,
        }


def _load_prompt(prompt_file: str) -> tuple[str, str, dict[str, Any]]:
    path = (
        Path(__file__).parent.parent.parent
        / "foundation" / "prompts" / "_defaults"
        / prompt_file
    )
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw.get("system", ""), raw.get("user", ""), raw.get("params", {})


def _extract_json(text: str) -> dict | list | None:
    """Extract and parse JSON, with bracket-closing repair on truncation."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    match = re.search(r"[\{\[].*[\}\]]", cleaned, re.DOTALL)
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


def _build_batch_spec(
    batch_idx: int, batch_size: int, seen: set[str], total: int,
) -> str:
    """Build batch instruction for the LLM."""
    if batch_idx == 0:
        n = min(batch_size, total)
        return (
            f"Output the first {n} signals/factors (of {total} total) "
            f"from the paper above. "
            "Output strict JSON (no descriptions, just name + formula)."
        )
    names = ", ".join(sorted(seen)[-15:])
    cap = min(batch_size, total - len(seen))
    return (
        f"Output the next signals/factors (at most {cap}, "
        f"~{total - len(seen)} remaining). "
        f"Already captured: {names}. "
        "DO NOT output these again. "
        "Output strict JSON (no descriptions, just name + formula)."
    )


def _parse_signals_from_response(response: str) -> list[SignalStub]:
    """Parse LLM response into SignalStub list."""
    parsed = _extract_json(response)
    if not parsed:
        return []
    if isinstance(parsed, dict) and "signals" in parsed:
        raw_list = parsed["signals"]
    elif isinstance(parsed, list):
        raw_list = parsed
    else:
        return []

    stubs: list[SignalStub] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        stubs.append(SignalStub(
            index=i + 1,
            name=name,
            formula_brief=str(item.get("formula", item.get("formula_brief", ""))),
            description=str(item.get("description", "")),
        ))
    return stubs


def _run_pass1(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    parsed_text: str,
) -> tuple[list[SignalStub], int, int]:
    """Run Pass 1: enumerate all signals.

    Uses batched LLM calls when plan estimates > BATCH_SIZE signals.
    Returns (list of SignalStub, latency_ms, n_calls).
    """
    total = (
        plan.n_signals_estimate
        if plan.n_signals_estimate > BATCH_SIZE and plan.confidence >= 0.8
        else 0
    )
    if total > 0:
        logger.info(
            "[track_b] paper=%s pass1: batching %d signals (size=%d, max_batches=%d)",
            paper_id, total, BATCH_SIZE, MAX_BATCHES,
        )
    system_text, user_template, params = _load_prompt(PROMPT_PASS1)
    tmpl = _jinja_env.from_string(user_template)

    if total == 0:
        # Single call (original behavior)
        user_msg = tmpl.render(
            paper_id=paper_id,
            paper_text=parsed_text,
            batch_spec="",
        )
        default_max = int(params.get("max_tokens", BATCH_MAX_TOKENS))
        budget_max = int(plan.token_budget.get("track_b_pass1", default_max))
        max_tokens = max(default_max, budget_max)

        t0 = time.monotonic()
        response = _call_chat_pass1(
            client,
            [{"role": "system", "content": system_text},
             {"role": "user", "content": user_msg}],
            max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        stubs = _parse_signals_from_response(response)
        if not stubs:
            logger.warning("[track_b] pass1 paper=%s JSON parse failed or empty", paper_id)
        logger.info(
            "[track_b] pass1 paper=%s enumerated %d signals (%dms)",
            paper_id, len(stubs), latency_ms,
        )
        return stubs, latency_ms, 1

    # Batched extraction
    seen_names: set[str] = set()
    all_stubs: list[SignalStub] = []
    total_latency = 0
    n_batches = min(math.ceil(total / BATCH_SIZE), MAX_BATCHES)

    for batch_idx in range(n_batches):
        logger.info(
            "[track_b] paper=%s pass1: batch %d/%d starting (%d/%d captured)",
            paper_id, batch_idx + 1, n_batches, len(all_stubs), total,
        )
        batch_spec = _build_batch_spec(batch_idx, BATCH_SIZE, seen_names, total)
        user_msg = tmpl.render(
            paper_id=paper_id,
            paper_text=parsed_text,
            batch_spec=batch_spec,
        )
        t0 = time.monotonic()
        response = _call_chat_pass1(
            client,
            [{"role": "system", "content": system_text},
             {"role": "user", "content": user_msg}],
            BATCH_MAX_TOKENS,
        )
        total_latency += int((time.monotonic() - t0) * 1000)

        stubs = _parse_signals_from_response(response)
        new = [s for s in stubs if s.name not in seen_names]
        for offset, s in enumerate(new, start=len(all_stubs) + 1):
            s.index = offset
        all_stubs.extend(new)
        seen_names |= {s.name for s in new}

        logger.info(
            "[track_b] paper=%s pass1: batch %d/%d done, got %d new (total %d/%d)",
            paper_id, batch_idx + 1, n_batches, len(new), len(all_stubs), total,
        )

        if len(new) < BATCH_SIZE:
            break

    logger.info(
        "[track_b] pass1 paper=%s batched=%d enumerated %d signals (%dms)",
        paper_id, n_batches, len(all_stubs), total_latency,
    )
    return all_stubs, total_latency, n_batches


def _run_pass2_one(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    signal_stub: SignalStub,
    parsed_text: str,
) -> SignalDetail:
    """Run Pass 2 for a single signal: extract L1-L4."""
    system_text, user_template, params = _load_prompt(PROMPT_PASS2)
    tmpl = _jinja_env.from_string(user_template)
    user_msg = tmpl.render(
        paper_id=paper_id,
        signal_name=signal_stub.name,
        formula_brief=signal_stub.formula_brief,
        signal_index=signal_stub.index,
        paper_text=parsed_text,
    )
    default_max = int(params.get("max_tokens", 5500))
    budget_max = int(
        plan.token_budget.get("track_b_pass2_per_factor", default_max)
    )
    max_tokens = max(default_max, budget_max)

    t0 = time.monotonic()
    try:
        response = _call_chat_pass2(
            client,
            [{"role": "system", "content": system_text},
             {"role": "user", "content": user_msg}],
            max_tokens,
        )
    except DeferError:
        raise
    except Exception as exc:
        return SignalDetail(
            name=signal_stub.name,
            success=False,
            error=f"llm_error: {exc}",
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

    parsed = _extract_json(response)
    if not parsed or not isinstance(parsed, dict):
        return SignalDetail(
            name=signal_stub.name,
            success=False,
            error="json_parse_failed",
            latency_ms=latency_ms,
        )

    # Extract L1-L4 from parsed result
    factor = parsed.get("factor", parsed)  # accept either nested or flat
    return SignalDetail(
        name=signal_stub.name,
        description=str(factor.get("description", signal_stub.description)),
        l1=factor.get("l1", {}),
        l2=factor.get("l2", {}),
        l3=factor.get("l3", {}),
        l4=factor.get("l4", {}),
        success=True,
        latency_ms=latency_ms,
    )


def _run_pass2_serial(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    signals: list[SignalStub],
    parsed_text: str,
) -> tuple[list[SignalDetail], int]:
    """Run Pass 2 for all signals serially (for now).

    Note: design calls for 3-way concurrency; using serial for
    simplicity (rate-limit friendly). Can switch to asyncio.gather
    with semaphore later.
    """
    logger.info(
        "[track_b] paper=%s pass2: %d factors starting (serial)",
        paper_id, len(signals),
    )
    details: list[SignalDetail] = []
    total_latency = 0
    for i, stub in enumerate(signals, 1):
        detail = _run_pass2_one(
            client, plan, paper_id, stub, parsed_text,
        )
        total_latency += detail.latency_ms
        details.append(detail)
        if i % 10 == 0 or i == len(signals):
            n_ok = sum(1 for d in details if d.success)
            logger.info(
                "[track_b] paper=%s pass2: %d/%d done (%d ok, %d failed)",
                paper_id, i, len(signals), n_ok, i - n_ok,
            )
        logger.info(
            "[track_b] pass2 %d/%d %s success=%s (%dms)",
            stub.index, len(signals), stub.name[:30],
            detail.success, detail.latency_ms,
        )
    return details, total_latency


def run_track_b(
    paper_id: str,
    parsed_text: str,
    plan: PlanResult,
    llm_client: Any | None = None,
    run_pass2: bool = True,
) -> TrackBResult:
    """Run Track B: factor-level extraction.

    Args:
        paper_id: Stable paper identifier.
        parsed_text: Full text from Stage 0.
        plan: Stage 1 Call 2 plan.
        llm_client: Optional pre-built LLM client.
        run_pass2: Whether to also run Pass 2 (L1-L4 per signal).
            Set False to just enumerate (Pass 1 only).

    Returns:
        TrackBResult with pass1_signals + pass2_details + stats.
    """
    enabled = plan.schema_choice != "summary"
    if not enabled:
        return TrackBResult(
            paper_id=paper_id,
            schema_choice=plan.schema_choice,
            enabled=False,
            success=True,  # skipped is not a failure
            error="skipped_summary_schema",
        )

    client = llm_client or build_default_client()
    t_total = time.monotonic()

    # Pass 1
    pass1_signals, pass1_latency, n_calls = _run_pass1(
        client, plan, paper_id, parsed_text,
    )

    if not pass1_signals:
        return TrackBResult(
            paper_id=paper_id,
            schema_choice=plan.schema_choice,
            enabled=True,
            pass1_latency_ms=pass1_latency,
            total_latency_ms=int((time.monotonic() - t_total) * 1000),
            llm_calls=n_calls,
            success=False,
            error="pass1_no_signals",
        )

    # Pass 2 (optional)
    pass2_details: list[SignalDetail] = []
    pass2_latency = 0
    n_complete = 0
    n_failed = 0
    if run_pass2:
        pass2_details, pass2_latency = _run_pass2_serial(
            client, plan, paper_id, pass1_signals, parsed_text,
        )
        n_calls += len(pass2_details)
        n_complete = sum(1 for d in pass2_details if d.success)
        n_failed = len(pass2_details) - n_complete

    total_latency = int((time.monotonic() - t_total) * 1000)

    return TrackBResult(
        paper_id=paper_id,
        schema_choice=plan.schema_choice,
        enabled=True,
        pass1_signals=pass1_signals,
        pass2_details=pass2_details,
        n_pass1=len(pass1_signals),
        n_pass2_complete=n_complete,
        n_pass2_failed=n_failed,
        pass1_latency_ms=pass1_latency,
        pass2_latency_ms=pass2_latency,
        pass2_concurrency=3,
        total_latency_ms=total_latency,
        llm_calls=n_calls,
        success=True,
    )
