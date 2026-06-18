"""Track B: Factor-level extraction (Pass 1 enumerate + Pass 2 detail).

Pass 1: enumerate all signals (name + brief formula) in one LLM call.
Pass 2: for each signal, extract L1-L4 in parallel LLM calls (default 3 concurrent).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from asyncio import Semaphore
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

# Checkpoint: save Pass 2 progress every N factors
PASS2_CHECKPOINT_INTERVAL = 10
PASS2_CHECKPOINT_FILENAME = "track_b_checkpoint.json"

# Parallel Pass 2 configuration
PASS2_MAX_CONCURRENCY = 3  # API limit: ≤3 concurrent (6 triggers throttle)
PASS2_CHECKPOINT_BATCH_SIZE = 10  # Save checkpoint every N completions
PASS2_USE_PARALLEL = True  # Toggle parallel/serial execution


@with_retry(stage="track_b_pass1", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_chat_pass1(client: Any, messages: list, max_tokens: int) -> str:
    """Pass 1 chat with L1 retry."""
    return client.chat(messages, max_tokens=max_tokens, temperature=0.1)


@with_retry(stage="track_b_pass2", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_chat_pass2(client: Any, messages: list, max_tokens: int) -> str:
    """Pass 2 per-factor chat with L1 retry."""
    return client.chat(messages, max_tokens=max_tokens, temperature=0.1)

# Multi-turn continuation parameters
MAX_ROUNDS = 10
MAX_CONSECUTIVE_ZERO = 2
PASS1_MAX_TOKENS_DEFAULT = 32000
PASS1_MAX_TOKENS_FALLBACK = 16384


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


# ── Checkpoint I/O ──────────────────────────────────────────


def _save_checkpoint(
    work_dir: Path,
    paper_id: str,
    pass1_signals: list[SignalStub],
    pass2_details: list[SignalDetail],
) -> None:
    """Save Pass 2 progress to disk for resume."""
    cp = {
        "paper_id": paper_id,
        "pass1_signals": [s.to_dict() for s in pass1_signals],
        "pass2_details": [d.to_dict() for d in pass2_details],
        "pass2_done_names": [d.name for d in pass2_details],
        "updated_at": time.time(),
    }
    cp_path = work_dir / PASS2_CHECKPOINT_FILENAME
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "[track_b] checkpoint saved: %s (%d pass1, %d pass2)",
        cp_path, len(pass1_signals), len(pass2_details),
    )


def _load_checkpoint(
    work_dir: Path,
) -> tuple[list[SignalStub], list[SignalDetail]] | None:
    """Load checkpoint from disk. Returns (pass1_signals, pass2_details) or None."""
    cp_path = work_dir / PASS2_CHECKPOINT_FILENAME
    if not cp_path.exists():
        return None
    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        pass1_signals = [
            SignalStub(**s) for s in data.get("pass1_signals", [])
        ]
        pass2_details = [
            SignalDetail(**d) for d in data.get("pass2_details", [])
        ]
        logger.info(
            "[track_b] checkpoint loaded: %s (%d pass1, %d pass2 done)",
            cp_path, len(pass1_signals), len(pass2_details),
        )
        return pass1_signals, pass2_details
    except Exception as exc:
        logger.warning("[track_b] checkpoint corrupted, starting fresh: %s", exc)
        return None


def _delete_checkpoint(work_dir: Path) -> None:
    """Delete checkpoint file after successful completion."""
    cp_path = work_dir / PASS2_CHECKPOINT_FILENAME
    if cp_path.exists():
        cp_path.unlink()
        logger.info("[track_b] checkpoint deleted: %s", cp_path)


def _parse_signals_from_response(response: str) -> tuple[list[SignalStub], bool]:
    """Parse LLM response into (list of SignalStub, done flag).

    Returns:
        (stubs, done): stubs = extracted signals from this response,
            done = whether LLM marked done: true.
    """
    parsed = _extract_json(response)
    if not parsed:
        return [], False
    done = False
    if isinstance(parsed, dict) and "signals" in parsed:
        raw_list = parsed["signals"]
        done = bool(parsed.get("done", False))
    elif isinstance(parsed, list):
        raw_list = parsed
        done = False
    else:
        return [], done

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
    return stubs, done


def _run_pass1(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    parsed_text: str,
) -> tuple[list[SignalStub], int, int]:
    """Run Pass 1: enumerate all signals via multi-turn continuation.

    Strategy: full paper in first message, max-output per round,
    continue with "continue" prompt until LLM signals done or we hit limits.
    Returns (list of SignalStub, latency_ms, n_calls).
    """
    system_text, user_template, params = _load_prompt(PROMPT_PASS1)
    tmpl = _jinja_env.from_string(user_template)
    default_max = int(params.get("max_tokens", PASS1_MAX_TOKENS_DEFAULT))
    budget_max = int(plan.token_budget.get("track_b_pass1", default_max))
    max_tokens = max(default_max, budget_max)

    # First round initial prompt
    user_msg_initial = tmpl.render(
        paper_id=paper_id,
        paper_text=parsed_text,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_msg_initial},
    ]
    seen_names: set[str] = set()
    all_stubs: list[SignalStub] = []
    total_latency = 0
    n_rounds = 0
    consecutive_zero = 0
    total_estimate = plan.n_signals_estimate

    logger.info(
        "[track_b] paper=%s pass1: multi-turn continuation starting "
        "(max_tokens=%d, estimate=%d signals)",
        paper_id, max_tokens, total_estimate,
    )

    while True:
        t0 = time.monotonic()
        try:
            response = _call_chat_pass1(
                client, messages, max_tokens,
            )
        except RuntimeError as exc:
            if "max_tokens" in str(exc) and max_tokens == PASS1_MAX_TOKENS_DEFAULT:
                # API doesn't support 32000, fallback to 16384
                max_tokens = PASS1_MAX_TOKENS_FALLBACK
                logger.warning(
                    "[track_b] paper=%s max_tokens=%d rejected by API, falling back to %d",
                    paper_id, PASS1_MAX_TOKENS_DEFAULT, PASS1_MAX_TOKENS_FALLBACK,
                )
                response = _call_chat_pass1(
                    client, messages, max_tokens,
                )
            else:
                raise
        latency_ms = int((time.monotonic() - t0) * 1000)
        total_latency += latency_ms
        n_rounds += 1

        stubs, done_llm = _parse_signals_from_response(response)
        new = [s for s in stubs if s.name not in seen_names]

        # Re-index and add
        for offset, s in enumerate(new, start=len(all_stubs) + 1):
            s.index = offset
        all_stubs.extend(new)
        seen_names |= {s.name for s in new}

        logger.info(
            "[track_b] paper=%s pass1 round %d/%d: got %d total %d/%d done_llm=%s",
            paper_id, n_rounds, MAX_ROUNDS, len(new), len(all_stubs),
            total_estimate, done_llm,
        )

        # Append to messages for next round
        messages.append({"role": "assistant", "content": response})

        # Check termination conditions (priority order)
        if done_llm:
            logger.info(
                "[track_b] paper=%s pass1 done: LLM marked done: true",
                paper_id,
            )
            break
        if len(all_stubs) >= total_estimate > 0:
            logger.info(
                "[track_b] paper=%s pass1 done: reached estimated count %d",
                paper_id, len(all_stubs),
            )
            break
        if len(new) == 0:
            consecutive_zero += 1
            if consecutive_zero >= MAX_CONSECUTIVE_ZERO:
                logger.info(
                    "[track_b] paper=%s pass1 done: %d consecutive zero new, stopping",
                    paper_id, MAX_CONSECUTIVE_ZERO,
                )
                break
        else:
            consecutive_zero = 0
        if n_rounds >= MAX_ROUNDS:
            logger.info(
                "[track_b] paper=%s pass1 done: reached max rounds %d",
                paper_id, MAX_ROUNDS,
            )
            break

        # Continue: add continuation prompt
        messages.append({
            "role": "user",
            "content": "继续输出剩余的所有信号因子，不重复之前已经输出的。全部完成后请输出 done: true。",
        })

    logger.info(
        "[track_b] pass1 paper=%s multi-turn=%d enumerated %d signals (%dms)",
        paper_id, n_rounds, len(all_stubs), total_latency,
    )
    return all_stubs, total_latency, n_rounds


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


async def _run_pass2_one_async(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    signal_stub: SignalStub,
    parsed_text: str,
    semaphore: Semaphore,
) -> tuple[SignalStub, SignalDetail]:
    """Async version of _run_pass2_one for parallel execution.

    Args:
        client: LLM client with achat() method.
        plan: Stage 1 Call 2 plan.
        paper_id: Paper identifier.
        signal_stub: Signal to extract.
        parsed_text: Full paper text.
        semaphore: Concurrency limiter.

    Returns:
        Tuple of (signal_stub, signal_detail) for result tracking.
    """
    async with semaphore:
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
            # Use async chat method
            response = await client.achat(
                [{"role": "system", "content": system_text},
                 {"role": "user", "content": user_msg}],
                max_tokens=max_tokens,
                temperature=0.1,
            )
        except DeferError:
            raise
        except Exception as exc:
            return signal_stub, SignalDetail(
                name=signal_stub.name,
                success=False,
                error=f"llm_error: {exc}",
            )
        latency_ms = int((time.monotonic() - t0) * 1000)

        parsed = _extract_json(response)
        if not parsed or not isinstance(parsed, dict):
            return signal_stub, SignalDetail(
                name=signal_stub.name,
                success=False,
                error="json_parse_failed",
                latency_ms=latency_ms,
            )

        # Extract L1-L4 from parsed result
        factor = parsed.get("factor", parsed)  # accept either nested or flat
        return signal_stub, SignalDetail(
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
    work_dir: Path | None = None,
    existing_details: list[SignalDetail] | None = None,
) -> tuple[list[SignalDetail], int]:
    """Run Pass 2 for all signals serially with checkpoint.

    Args:
        work_dir: If provided, save checkpoint every PASS2_CHECKPOINT_INTERVAL factors.
        existing_details: If provided (resume), skip factors already in this list.
    """
    done_names = {d.name for d in existing_details} if existing_details else set()
    remaining = [s for s in signals if s.name not in done_names]
    details: list[SignalDetail] = list(existing_details) if existing_details else []
    total_latency = sum(d.latency_ms for d in details)

    if done_names:
        logger.info(
            "[track_b] paper=%s pass2: resuming %d/%d factors (%d already done)",
            paper_id, len(remaining), len(signals), len(done_names),
        )
    else:
        logger.info(
            "[track_b] paper=%s pass2: %d factors starting (serial)",
            paper_id, len(signals),
        )

    for i, stub in enumerate(remaining, 1):
        global_idx = len(details) + 1
        detail = _run_pass2_one(
            client, plan, paper_id, stub, parsed_text,
        )
        total_latency += detail.latency_ms
        details.append(detail)

        # Log every factor
        logger.info(
            "[track_b] pass2 %d/%d %s success=%s (%dms)",
            global_idx, len(signals), stub.name[:30],
            detail.success, detail.latency_ms,
        )

        # Log progress + checkpoint every N factors
        if global_idx % PASS2_CHECKPOINT_INTERVAL == 0 or global_idx == len(signals):
            n_ok = sum(1 for d in details if d.success)
            n_fail = len(details) - n_ok
            logger.info(
                "[track_b] paper=%s pass2: %d/%d done (%d ok, %d failed)",
                paper_id, global_idx, len(signals), n_ok, n_fail,
            )
            if work_dir:
                _save_checkpoint(work_dir, paper_id, signals, details)

    # Final checkpoint
    if work_dir and remaining:
        _save_checkpoint(work_dir, paper_id, signals, details)

    return details, total_latency


async def _run_pass2_parallel(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    signals: list[SignalStub],
    parsed_text: str,
    work_dir: Path | None = None,
    existing_details: list[SignalDetail] | None = None,
) -> tuple[list[SignalDetail], int]:
    """Run Pass 2 for all signals in parallel with checkpoint.

    Uses asyncio.Semaphore to limit concurrency to PASS2_MAX_CONCURRENCY.
    Results are collected as they complete and checkpointed in batches.

    Args:
        client: LLM client with achat() method.
        plan: Stage 1 Call 2 plan.
        paper_id: Paper identifier.
        signals: All signal stubs from Pass 1.
        parsed_text: Full paper text.
        work_dir: If provided, save checkpoint every PASS2_CHECKPOINT_BATCH_SIZE factors.
        existing_details: If provided (resume), skip factors already in this list.

    Returns:
        Tuple of (list of SignalDetail, total_latency_ms).
    """
    done_names = {d.name for d in existing_details} if existing_details else set()
    remaining = [s for s in signals if s.name not in done_names]
    details: list[SignalDetail] = list(existing_details) if existing_details else []
    total_latency = sum(d.latency_ms for d in details)

    if done_names:
        logger.info(
            "[track_b] paper=%s pass2: resuming %d/%d factors (%d already done)",
            paper_id, len(remaining), len(signals), len(done_names),
        )
    else:
        logger.info(
            "[track_b] paper=%s pass2: %d factors starting (parallel, concurrency=%d)",
            paper_id, len(signals), PASS2_MAX_CONCURRENCY,
        )

    semaphore = Semaphore(PASS2_MAX_CONCURRENCY)

    # Create all tasks
    tasks = [
        _run_pass2_one_async(client, plan, paper_id, stub, parsed_text, semaphore)
        for stub in remaining
    ]

    # Collect results as they complete
    completed = 0
    for coro in asyncio.as_completed(tasks):
        stub, detail = await coro
        total_latency += detail.latency_ms
        details.append(detail)
        completed += 1

        # Log every factor
        global_idx = len(details)
        logger.info(
            "[track_b] pass2 %d/%d %s success=%s (%dms)",
            global_idx, len(signals), stub.name[:30],
            detail.success, detail.latency_ms,
        )

        # Log progress + checkpoint every batch
        if completed % PASS2_CHECKPOINT_BATCH_SIZE == 0 or completed == len(remaining):
            n_ok = sum(1 for d in details if d.success)
            n_fail = len(details) - n_ok
            logger.info(
                "[track_b] paper=%s pass2: %d/%d done (%d ok, %d failed)",
                paper_id, global_idx, len(signals), n_ok, n_fail,
            )
            if work_dir:
                _save_checkpoint(work_dir, paper_id, signals, details)

    # Final checkpoint
    if work_dir and remaining:
        _save_checkpoint(work_dir, paper_id, signals, details)

    return details, total_latency


def run_track_b(
    paper_id: str,
    parsed_text: str,
    plan: PlanResult,
    llm_client: Any | None = None,
    run_pass2: bool = True,
    work_dir: Path | None = None,
) -> TrackBResult:
    """Run Track B: factor-level extraction with checkpoint resume.

    Args:
        paper_id: Stable paper identifier.
        parsed_text: Full text from Stage 0.
        plan: Stage 1 Call 2 plan.
        llm_client: Optional pre-built LLM client.
        run_pass2: Whether to also run Pass 2 (L1-L4 per signal).
        work_dir: Paper work directory. If provided, checkpoint is saved
            every PASS2_CHECKPOINT_INTERVAL factors and used for resume.

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

    # Check for existing checkpoint (resume)
    pass1_signals: list[SignalStub] = []
    pass2_details_done: list[SignalDetail] = []
    n_calls = 0
    pass1_latency = 0

    if work_dir:
        ckpt = _load_checkpoint(work_dir)
        if ckpt:
            pass1_signals, pass2_details_done = ckpt
            n_calls = len(pass2_details_done)  # approximate
            logger.info(
                "[track_b] paper=%s resuming from checkpoint: %d pass1, %d pass2 done",
                paper_id, len(pass1_signals), len(pass2_details_done),
            )

    # Pass 1 (skip if resuming from checkpoint)
    if not pass1_signals:
        pass1_signals, pass1_latency, n_calls = _run_pass1(
            client, plan, paper_id, parsed_text,
        )
        if work_dir and pass1_signals:
            _save_checkpoint(work_dir, paper_id, pass1_signals, [])

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

    # Pass 2 (optional, with resume)
    pass2_details: list[SignalDetail] = []
    pass2_latency = 0
    if run_pass2:
        # Choose parallel or serial execution based on configuration
        if PASS2_USE_PARALLEL:
            pass2_details, pass2_latency = asyncio.run(
                _run_pass2_parallel(
                    client, plan, paper_id, pass1_signals, parsed_text,
                    work_dir=work_dir,
                    existing_details=pass2_details_done or None,
                )
            )
        else:
            pass2_details, pass2_latency = _run_pass2_serial(
                client, plan, paper_id, pass1_signals, parsed_text,
                work_dir=work_dir,
                existing_details=pass2_details_done or None,
            )
        n_calls += len(pass2_details) - len(pass2_details_done)
        # Delete checkpoint on completion
        if work_dir:
            _delete_checkpoint(work_dir)

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
        pass2_concurrency=PASS2_MAX_CONCURRENCY if PASS2_USE_PARALLEL else 1,
        total_latency_ms=total_latency,
        llm_calls=n_calls,
        success=True,
    )
