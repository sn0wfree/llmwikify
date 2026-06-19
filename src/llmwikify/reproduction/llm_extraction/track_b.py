"""Track B: Factor-level extraction (Pass 1 enumerate + Pass 2 detail).

Pass 1: enumerate all signals (name + brief formula) in one LLM call.
Pass 2: for each signal, extract L1-L4 in parallel LLM calls (default 3 concurrent).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
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
PROMPT_PASS2_SUPPLEMENT = "repro_extract_track_b_pass2_supplement.yaml"

API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}

# Checkpoint: save Pass 2 progress every N factors
PASS2_CHECKPOINT_INTERVAL = 10
PASS2_CHECKPOINT_FILENAME = "track_b_checkpoint.json"

# Adaptive Pass 2 multi-turn configuration (v2)
ADAPTIVE_CONTEXT_VERSION = "v2_adaptive"
PASS2_BATCH_SIZE = 3              # signals per LLM call in adaptive mode
PASS2_MAX_HISTORY_MESSAGES = 20   # keep system + most recent 20 (user, asst) pairs
PASS2_MAX_SUPPLEMENTS_PER_SIGNAL = 5  # per-signal max supplemental requests
PASS2_MAX_TOTAL_ROUNDS = 200      # safety cap on total rounds

# Parallel Pass 2 configuration
PASS2_MAX_CONCURRENCY = 3  # API limit: ≤3 concurrent (6 triggers throttle)
PASS2_CHECKPOINT_BATCH_SIZE = 10  # Save checkpoint every N completions
PASS2_USE_PARALLEL = True  # Toggle parallel/serial execution
PASS2_USE_ADAPTIVE = True  # Use adaptive multi-turn (v2, recommended)

# Smart mode selection (v3.0)
PASS2_MODE_AUTO = True       # Auto-select based on complexity
PASS2_MODE_OVERRIDE = os.getenv("PASS2_MODE_OVERRIDE", "")  # L1 env var: "adaptive" | "parallel" | "serial" | "hybrid" | ""
# Complexity thresholds for auto-selection
ADAPTIVE_MIN_SIGNALS = 20    # < 20 signals → use parallel (less overhead)
ADAPTIVE_MAX_SIGNALS = 200   # > 200 signals → use parallel (multi-turn too slow)
ADAPTIVE_AVG_FORMULA_LEN = 80  # > 80 chars avg formula → use parallel (complex)
ADAPTIVE_AVG_CONTEXT_LEN = 2000  # < 2000 chars avg context → use parallel (likely complex)

# Hybrid mode (v3.1): parallel first, then adaptive supplement for shallow factors
PASS2_HYBRID_ENABLED = True  # Allow "hybrid" as Pass 2 mode
HYBRID_INTUITION_THRESHOLD = 150  # l3.intuition < this chars → shallow, needs supplement
HYBRID_THEORETICAL_MIN = 50  # l3.theoretical_basis < this chars → shallow
HYBRID_HYPOTHESES_MIN = 2    # l4.hypotheses count < this → shallow
HYBRID_SUPPLEMENT_RATIO = 0.2  # Supplement at most 20% of factors with adaptive
HYBRID_MIN_SUPPLEMENTS = 3    # Always supplement at least this many (if any)
HYBRID_SUPPLEMENT_BATCH_SIZE = 4   # Supplement signals per LLM call (batch)
HYBRID_SUPPLEMENT_CONCURRENCY = 3  # Max concurrent batches for supplement phase
HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT = True  # Use PROMPT_PASS2_SUPPLEMENT instead of adaptive multi-turn

# Success rate thresholds for auto-retry
PASS2_SUCCESS_THRESHOLD_HIGH = 0.95  # 95%: Complete, no retry needed
PASS2_SUCCESS_THRESHOLD_LOW = 0.80   # 80%: Retry failed factors
PASS2_MAX_RETRY_ROUNDS = 1           # Maximum retry rounds


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
    """Pass 1 output: brief signal enumeration.

    Adaptive Pass 2 fields (v2):
    - context_excerpt: ~3000 chars paper excerpt (adaptive: 1000-10000)
    - context_start/end: char positions in paper_text for verification
    """
    index: int
    name: str
    formula_brief: str
    description: str = ""
    # Adaptive Pass 2 multi-turn (added in v2)
    context_excerpt: str = ""
    context_start: int = 0
    context_end: int = 0

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
    # New fields for success rate and retry
    success_rate: float = 0.0  # Success rate (0.0 - 1.0)
    retry_rounds: int = 0      # Number of retry rounds performed
    needs_retry: bool = False  # Whether more retries are needed

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
            "success_rate": self.success_rate,
            "retry_rounds": self.retry_rounds,
            "needs_retry": self.needs_retry,
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
        "context_version": ADAPTIVE_CONTEXT_VERSION,
    }
    cp_path = work_dir / PASS2_CHECKPOINT_FILENAME
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "[track_b] checkpoint saved: %s (%d pass1, %d pass2, version=%s)",
        cp_path, len(pass1_signals), len(pass2_details), ADAPTIVE_CONTEXT_VERSION,
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


def _get_signal_context(signal: SignalStub, parsed_text: str) -> str:
    """Get context for a signal, with backward-compat fallback (Option B).

    New SignalStub (has context_excerpt): use it directly.
    Old SignalStub (no context_excerpt): use paper slice based on signal.index.

    Args:
        signal: SignalStub from Pass 1.
        parsed_text: Full paper text.

    Returns:
        Context string to use for Pass 2 extraction.
    """
    if signal.context_excerpt and len(signal.context_excerpt) > 50:
        return signal.context_excerpt

    # Fallback: paper slice based on signal index (for old SignalStub)
    paper_start = (signal.index - 1) * 5000
    paper_end = paper_start + 5000
    if paper_end > len(parsed_text):
        paper_end = len(parsed_text)
    if paper_start > len(parsed_text):
        paper_start = max(0, len(parsed_text) - 5000)
    logger.warning(
        "[pass2] signal %s: no context_excerpt (old checkpoint?), "
        "using paper slice [%d:%d]",
        signal.name, paper_start, paper_end,
    )
    return parsed_text[paper_start:paper_end]


def estimate_complexity(stubs: list[SignalStub]) -> dict:
    """Estimate extraction complexity from Pass 1 signals.

    Heuristics:
    - Signal count: too few (overhead) or too many (multi-turn slow) → parallel
    - Avg formula length: long formulas → complex → parallel better
    - Avg context_excerpt length: short context → LLM will request many
      supplements → parallel might be better

    Returns:
        dict with:
        - signal_count: int
        - avg_formula_len: float
        - avg_context_len: float
        - complexity_score: float (0.0-1.0, higher = more complex)
        - recommendation: "adaptive" | "parallel"
        - reasons: list[str] explaining the recommendation
    """
    if not stubs:
        return {
            "signal_count": 0,
            "avg_formula_len": 0,
            "avg_context_len": 0,
            "complexity_score": 0.5,
            "recommendation": "parallel",
            "reasons": ["no signals found"],
        }

    n = len(stubs)
    formula_lens = [len(s.formula_brief or "") for s in stubs]
    context_lens = [len(s.context_excerpt or "") for s in stubs]
    avg_formula = sum(formula_lens) / n
    avg_context = sum(context_lens) / n

    # Complexity score (0-1)
    # Each factor contributes 0-0.33
    signal_factor = 0.0
    if n < ADAPTIVE_MIN_SIGNALS:
        signal_factor = 0.0  # Too few, no benefit from multi-turn
    elif n > ADAPTIVE_MAX_SIGNALS:
        signal_factor = 0.4  # Too many, multi-turn too slow
    else:
        signal_factor = 0.0  # In sweet spot

    formula_factor = min(0.3, avg_formula / 300)  # 0-0.3 based on formula length
    context_factor = 0.0 if avg_context >= 1500 else 0.3  # Short context = complex

    score = signal_factor + formula_factor + context_factor

    # Decision logic
    reasons = []
    use_adaptive = True

    if n < ADAPTIVE_MIN_SIGNALS:
        use_adaptive = False
        reasons.append(
            f"only {n} signals (< {ADAPTIVE_MIN_SIGNALS}); parallel has less overhead"
        )
    elif n > ADAPTIVE_MAX_SIGNALS:
        use_adaptive = False
        reasons.append(
            f"{n} signals (> {ADAPTIVE_MAX_SIGNALS}); multi-turn would be too slow"
        )

    if avg_formula > ADAPTIVE_AVG_FORMULA_LEN:
        use_adaptive = False
        reasons.append(
            f"avg formula {avg_formula:.0f} chars (> {ADAPTIVE_AVG_FORMULA_LEN}); "
            f"complex formulas cause excessive need_more requests"
        )

    if avg_context < ADAPTIVE_AVG_CONTEXT_LEN:
        use_adaptive = False
        reasons.append(
            f"avg context {avg_context:.0f} chars (< {ADAPTIVE_AVG_CONTEXT_LEN}); "
            f"short context triggers many supplements"
        )

    if not reasons:
        reasons.append(
            f"{n} signals, avg formula {avg_formula:.0f} chars, "
            f"avg context {avg_context:.0f} chars: good for adaptive"
        )

    return {
        "signal_count": n,
        "avg_formula_len": avg_formula,
        "avg_context_len": avg_context,
        "complexity_score": round(score, 3),
        "recommendation": "adaptive" if use_adaptive else "parallel",
        "reasons": reasons,
    }


def select_pass2_mode(stubs: list[SignalStub]) -> str:
    """Select Pass 2 execution mode based on override and complexity.

    Priority:
    1. PASS2_MODE_OVERRIDE (if set): force this mode
    2. PASS2_MODE_AUTO = True: use estimate_complexity() (may return "hybrid")
    3. Default to PASS2_USE_ADAPTIVE / PASS2_USE_PARALLEL flags

    Returns: "adaptive" | "parallel" | "serial" | "hybrid"
    """
    if PASS2_MODE_OVERRIDE:
        mode = PASS2_MODE_OVERRIDE.lower()
        if mode in ("adaptive", "parallel", "serial", "hybrid"):
            logger.info(
                "[track_b] pass2 mode: %s (override)", mode,
            )
            return mode
        logger.warning(
            "[track_b] invalid PASS2_MODE_OVERRIDE=%s, falling back to auto",
            mode,
        )

    if PASS2_MODE_AUTO:
        complexity = estimate_complexity(stubs)
        # Hybrid mode: prefer when complexity score suggests adaptive but
        # signal count is high (would be slow pure adaptive)
        if (
            PASS2_HYBRID_ENABLED
            and complexity["recommendation"] == "adaptive"
            and complexity["signal_count"] >= 30
        ):
            logger.info(
                "[track_b] complexity: signals=%d avg_formula=%.0f avg_context=%.0f "
                "score=%.2f → HYBRID (parallel + adaptive supplement). "
                "Reasons: %s",
                complexity["signal_count"],
                complexity["avg_formula_len"],
                complexity["avg_context_len"],
                complexity["complexity_score"],
                "; ".join(complexity["reasons"]),
            )
            return "hybrid"
        logger.info(
            "[track_b] complexity: signals=%d avg_formula=%.0f avg_context=%.0f "
            "score=%.2f → %s. Reasons: %s",
            complexity["signal_count"],
            complexity["avg_formula_len"],
            complexity["avg_context_len"],
            complexity["complexity_score"],
            complexity["recommendation"],
            "; ".join(complexity["reasons"]),
        )
        return complexity["recommendation"]

    # Fallback to flags
    if PASS2_USE_ADAPTIVE:
        return "adaptive"
    if PASS2_USE_PARALLEL:
        return "parallel"
    return "serial"


def _assess_factor_quality(detail: SignalDetail) -> dict:
    """Assess if a factor needs adaptive supplementation (hybrid mode).

    Returns dict with:
        - needs_supplement: bool
        - shallow_score: float (0-1, higher = more shallow)
        - reasons: list[str]
        - l3_intuition_chars: int
        - l3_theoretical_chars: int
        - l4_hypotheses_count: int

    A factor is "shallow" if any of:
    - l3.intuition (or financial_intuition) < HYBRID_INTUITION_THRESHOLD (150 chars)
    - l3.theoretical_basis < HYBRID_THEORETICAL_MIN (50 chars)
    - l4.hypotheses count < HYBRID_HYPOTHESES_MIN (2)
    - factor failed (success=False)

    Shallow factors benefit most from adaptive multi-turn supplementation.

    Schema compat:
    - New (v2.0+): l3.financial_intuition
    - Legacy: l3.intuition
    """
    l3 = detail.l3 or {}
    l4 = detail.l4 or {}
    # Schema compat: financial_intuition (new) or intuition (legacy)
    l3_intuition = l3.get("financial_intuition") or l3.get("intuition") or ""
    l3_intuition_str = str(l3_intuition)
    l3_intuition_chars = len(l3_intuition_str)

    l3_theoretical = l3.get("theoretical_basis", "") or ""
    l3_theoretical_str = str(l3_theoretical)
    l3_theoretical_chars = len(l3_theoretical_str)

    hypotheses = l4.get("hypotheses", []) or []
    l4_hypotheses_count = len(hypotheses) if isinstance(hypotheses, list) else 0

    reasons = []
    shallow_score = 0.0

    if not detail.success:
        reasons.append("factor_failed")
        shallow_score += 1.0

    if l3_intuition_chars < HYBRID_INTUITION_THRESHOLD:
        reasons.append(f"l3.intuition short ({l3_intuition_chars} chars)")
        shallow_score += 0.4

    if l3_theoretical_chars < HYBRID_THEORETICAL_MIN:
        reasons.append(f"l3.theoretical_basis short ({l3_theoretical_chars} chars)")
        shallow_score += 0.3

    if l4_hypotheses_count < HYBRID_HYPOTHESES_MIN:
        reasons.append(f"l4.hypotheses few ({l4_hypotheses_count})")
        shallow_score += 0.3

    return {
        "needs_supplement": shallow_score > 0,
        "shallow_score": round(shallow_score, 3),
        "reasons": reasons,
        "l3_intuition_chars": l3_intuition_chars,
        "l3_theoretical_chars": l3_theoretical_chars,
        "l4_hypotheses_count": l4_hypotheses_count,
    }


def _select_supplement_targets(
    details: list[SignalDetail],
    stubs: list[SignalStub],
    parsed_text: str,
) -> tuple[list[SignalStub], list[SignalDetail]]:
    """Select shallow factors to supplement via adaptive multi-turn.

    Args:
        details: SignalDetail list from parallel Pass 2.
        stubs: Original SignalStub list (in same order).
        parsed_text: Full paper text (unused, reserved for future).

    Returns:
        (supplement_stubs, supplement_details) where:
        - supplement_stubs: SignalStub to re-process via adaptive
        - supplement_details: original SignalDetail objects to replace
    """
    stub_by_name = {s.name: s for s in stubs}

    # Assess all details
    assessments = []
    for d in details:
        a = _assess_factor_quality(d)
        if a["needs_supplement"]:
            assessments.append((d, a))

    # Sort by shallow_score desc (most shallow first)
    assessments.sort(key=lambda x: x[1]["shallow_score"], reverse=True)

    # Calculate how many to supplement (HYBRID_SUPPLEMENT_RATIO of total)
    n_total = len(details)
    n_to_supplement = max(
        HYBRID_MIN_SUPPLEMENTS,
        int(n_total * HYBRID_SUPPLEMENT_RATIO),
    )
    # Don't exceed available shallow factors
    n_to_supplement = min(n_to_supplement, len(assessments))

    supplement_stubs: list[SignalStub] = []
    supplement_details: list[SignalDetail] = []
    for d, _a in assessments[:n_to_supplement]:
        stub = stub_by_name.get(d.name)
        if stub:
            supplement_stubs.append(stub)
            supplement_details.append(d)

    return supplement_stubs, supplement_details


def _hybrid_pass2(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    signals: list[SignalStub],
    parsed_text: str,
    work_dir: Path | None = None,
    existing_details: list[SignalDetail] | None = None,
) -> tuple[list[SignalDetail], int]:
    """Hybrid Pass 2: parallel first, adaptive supplement for shallow factors.

    Workflow:
    1. Run Pass 2 in parallel (3-way) for all signals - fast (~30 min for 101)
    2. Assess each factor's quality (l3.intuition depth, l4.hypotheses count, etc.)
    3. Select bottom 20% shallow factors (max)
    4. Re-process those factors via adaptive multi-turn - deep
    5. Merge: keep original successes, replace shallow with adaptive results

    Args:
        client: LLM client.
        plan: PlanResult.
        paper_id: Paper identifier.
        signals: Pass 1 signal stubs.
        parsed_text: Full paper text.
        work_dir: For checkpointing (optional).
        existing_details: Resume from checkpoint.

    Returns:
        (details, total_latency_ms) where details is the merged list.
    """
    logger.info(
        "[track_b] paper=%s pass2 HYBRID: phase 1 = parallel (%d signals)",
        paper_id, len(signals),
    )

    # Phase 1: Parallel (fast)
    parallel_details, parallel_latency = asyncio.run(
        _run_pass2_parallel(
            client, plan, paper_id, signals, parsed_text,
            work_dir=work_dir,
            existing_details=existing_details,
        )
    )

    # Phase 2: Assess quality
    supplement_stubs, supplement_details = _select_supplement_targets(
        parallel_details, signals, parsed_text,
    )

    if not supplement_stubs:
        logger.info(
            "[track_b] paper=%s pass2 HYBRID: no shallow factors, done",
            paper_id,
        )
        return parallel_details, parallel_latency

    logger.info(
        "[track_b] paper=%s pass2 HYBRID: phase 2 = adaptive supplement "
        "(%d/%d shallow factors, prompt=%s)",
        paper_id, len(supplement_stubs), len(signals),
        PROMPT_PASS2_SUPPLEMENT if HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT else PROMPT_PASS2,
    )

    # Phase 3: Adaptive multi-turn for shallow factors.
    # When HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT=True, use PROMPT_PASS2_SUPPLEMENT
    # which emphasizes L3/L4 depth (vs general pass 2).
    supplement_prompt = (
        PROMPT_PASS2_SUPPLEMENT
        if HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT
        else PROMPT_PASS2
    )
    adaptive_details, adaptive_latency = asyncio.run(
        _run_pass2_adaptive(
            client, plan, paper_id, supplement_stubs, parsed_text,
            prompt_file=supplement_prompt,
        )
    )

    # Phase 4: Merge - replace original shallow with adaptive results
    supplement_names = {d.name for d in supplement_details}
    final_details: list[SignalDetail] = []
    replaced = 0
    for d in parallel_details:
        if d.name in supplement_names:
            # Find adaptive replacement
            replacement = next((a for a in adaptive_details if a.name == d.name), None)
            if replacement:
                final_details.append(replacement)
                replaced += 1
            else:
                # Keep original if adaptive failed
                final_details.append(d)
        else:
            final_details.append(d)

    # Track which ones improved
    improved = 0
    for orig in supplement_details:
        new = next((d for d in final_details if d.name == orig.name), None)
        if new and new.success:
            orig_intuition = (orig.l3 or {}).get("intuition", "") or ""
            new_intuition = (new.l3 or {}).get("intuition", "") or ""
            if len(str(new_intuition)) > len(str(orig_intuition)):
                improved += 1

    total_latency = parallel_latency + adaptive_latency
    logger.info(
        "[track_b] paper=%s pass2 HYBRID: complete "
        "(%d replaced, %d improved, %dms parallel + %dms adaptive = %dms total)",
        paper_id, replaced, improved,
        parallel_latency, adaptive_latency, total_latency,
    )

    return final_details, total_latency


def _supplement_context(
    signal: SignalStub,
    need_info: dict,
    parsed_text: str,
) -> str:
    """Generate supplemental context based on LLM's level request.

    Levels:
        a: paragraph level (1000-2000 chars)
        b: section level (5000-8000 chars)
        c: full paper

    Args:
        signal: SignalStub (for context_start reference).
        need_info: Dict with 'level' key.
        parsed_text: Full paper text.

    Returns:
        Supplemental context string.
    """
    level = need_info.get("level", "a")

    if level == "c":
        # Full paper
        return parsed_text

    if level == "b":
        # Section level: 5000-8000 chars
        # Use context_start as anchor, expand to ~7000 chars
        start = max(0, signal.context_start - 1000)
        end = min(len(parsed_text), start + 7000)
        # If we hit end of paper, also extend backward
        if end - start < 5000 and start > 0:
            start = max(0, end - 7000)
        return parsed_text[start:end]

    # Default: level a (paragraph level: 1000-2000 chars)
    start = max(0, signal.context_start)
    end = min(len(parsed_text), start + 2000)
    return parsed_text[start:end]


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
        # context_excerpt: support either string or absent (backward-compat)
        ctx_raw = item.get("context_excerpt", "")
        if not isinstance(ctx_raw, str):
            ctx_raw = ""
        # context_start/end: best-effort int parse
        try:
            ctx_start = int(item.get("context_start", 0) or 0)
        except (TypeError, ValueError):
            ctx_start = 0
        try:
            ctx_end = int(item.get("context_end", 0) or 0)
        except (TypeError, ValueError):
            ctx_end = 0
        stubs.append(SignalStub(
            index=i + 1,
            name=name,
            formula_brief=str(item.get("formula", item.get("formula_brief", ""))),
            description=str(item.get("description", "")),
            context_excerpt=ctx_raw,
            context_start=ctx_start,
            context_end=ctx_end,
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
    """Run Pass 2 for a single signal: extract L1-L4.

    Uses batch mode (v2.0+) for consistency with adaptive multi-turn.
    """
    system_text, user_template, params = _load_prompt(PROMPT_PASS2)
    tmpl = _jinja_env.from_string(user_template)
    context = _get_signal_context(signal_stub, parsed_text)
    user_msg = tmpl.render(
        paper_id=paper_id,
        round_idx=1,
        batch_size=1,
        signals=[{
            "name": signal_stub.name,
            "formula_brief": signal_stub.formula_brief,
            "context_excerpt": context,
        }],
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

    # Extract L1-L4 from parsed result (v2.0+ batch mode)
    factors_list = _unwrap_factors(parsed)
    if factors_list and isinstance(factors_list, list) and factors_list:
        factor = factors_list[0]  # batch_size=1, take first
    else:
        # Legacy single-factor format
        factor = parsed.get("factor", parsed)
    if not isinstance(factor, dict):
        return SignalDetail(
            name=signal_stub.name,
            success=False,
            error="invalid_factor_format",
            latency_ms=latency_ms,
        )
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
        # Use batch mode (v2.0+) for consistency with adaptive
        context = _get_signal_context(signal_stub, parsed_text)
        user_msg = tmpl.render(
            paper_id=paper_id,
            round_idx=1,
            batch_size=1,
            signals=[{
                "name": signal_stub.name,
                "formula_brief": signal_stub.formula_brief,
                "context_excerpt": context,
            }],
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

        # Extract L1-L4 from parsed result (v2.0+ batch mode: {"factors": [{...}]})
        factors_list = _unwrap_factors(parsed)
        if factors_list and isinstance(factors_list, list) and factors_list:
            factor = factors_list[0]  # batch_size=1, take first
        else:
            # Legacy single-factor format
            factor = parsed.get("factor", parsed)
        if not isinstance(factor, dict):
            return signal_stub, SignalDetail(
                name=signal_stub.name,
                success=False,
                error="invalid_factor_format",
                latency_ms=latency_ms,
            )
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


def _unwrap_factors(parsed: Any) -> list | None:
    """Unwrap JSON response to a list of factor dicts.

    Accepts:
    - {"factors": [...]}
    - [...]
    - {"factor": {...}}  (legacy single-signal)
    Returns list of dicts or None on failure.
    """
    if parsed is None:
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if "factors" in parsed and isinstance(parsed["factors"], list):
            return parsed["factors"]
        if "factor" in parsed and isinstance(parsed["factor"], dict):
            # Legacy single-factor format → wrap in list
            return [parsed["factor"]]
    return None


def _build_signal_detail(stub: SignalStub, factor: dict, latency_ms: int) -> SignalDetail:
    """Build SignalDetail from a factor dict.

    Handles both new (l1/l2/l3/l4 nested) and legacy (flat) schemas.
    """
    if not isinstance(factor, dict):
        return SignalDetail(
            name=stub.name, success=False,
            error="invalid_factor_format", latency_ms=latency_ms,
        )
    # New format: factor has l1/l2/l3/l4 keys
    l1 = factor.get("l1", {})
    l2 = factor.get("l2", {})
    l3 = factor.get("l3", {})
    l4 = factor.get("l4", {})
    return SignalDetail(
        name=stub.name,
        description=str(factor.get("description", stub.description)),
        l1=l1 if isinstance(l1, dict) else {},
        l2=l2 if isinstance(l2, dict) else {},
        l3=l3 if isinstance(l3, dict) else {},
        l4=l4 if isinstance(l4, dict) else {},
        success=True,
        latency_ms=latency_ms,
    )


def _render_user_msg(tmpl, paper_id: str, round_idx: int, batch: list[SignalStub], parsed_text: str = "") -> str:
    """Render user message for one batch in adaptive multi-turn.

    Args:
        tmpl: Jinja2 template for the user message.
        paper_id: Paper identifier.
        round_idx: Current round number (1-indexed).
        batch: List of SignalStub to extract in this batch.
        parsed_text: Full paper text (for context fallback if SignalStub lacks context_excerpt).
    """
    rendered_signals = []
    for sig in batch:
        ctx = _get_signal_context(sig, parsed_text)
        rendered_signals.append({
            "name": sig.name,
            "formula_brief": sig.formula_brief,
            "context_excerpt": ctx,
        })
    return tmpl.render(
        paper_id=paper_id,
        round_idx=round_idx,
        batch_size=len(batch),
        signals=rendered_signals,
    )


def _render_supplement_msg(
    need_supplement: list[tuple[SignalStub, dict]],
    parsed_text: str,
) -> str:
    """Render supplemental context message for signals needing more info."""
    parts = ["以下信号需要更多上下文以完成提取。已补充相应 paper 切片：\n"]
    for sig, need_info in need_supplement:
        level = need_info.get("level", "a")
        reason = need_info.get("reason", "")
        section_hint = need_info.get("section_hint", "")
        supplement = _supplement_context(sig, need_info, parsed_text)
        parts.append(
            f"\n--- Signal: {sig.name} (level={level}) ---\n"
            f"Reason: {reason}\n"
            f"Section hint: {section_hint or '(none)'}\n"
            f"Supplemental context ({len(supplement)} chars):\n"
            f"{supplement}\n"
        )
    parts.append(
        "\n请基于补充的上下文，重新提取这些信号的 L1-L4。"
    )
    return "".join(parts)


async def _run_pass2_adaptive(
    client: Any,
    plan: PlanResult,
    paper_id: str,
    signals: list[SignalStub],
    parsed_text: str,
    work_dir: Path | None = None,
    existing_details: list[SignalDetail] | None = None,
    prompt_file: str = PROMPT_PASS2,
) -> tuple[list[SignalDetail], int]:
    """Run Pass 2 with adaptive multi-turn: LLM self-assesses context, requests a/b/c.

    Args:
        prompt_file: Prompt template filename. Defaults to PROMPT_PASS2.
            Set to PROMPT_PASS2_SUPPLEMENT for deep refinement mode (hybrid).

    Algorithm:
    1. Initialize single session with system prompt
    2. For each batch of 3 signals:
       a. Render user message with formula_brief + context_excerpt
       b. Call LLM (multi-turn accumulates messages)
       c. Parse response, identify completed vs need_more_context
       d. For need_more: send supplemental context (a/b/c level)
       e. Continue until all signals done or per-signal max (5) supplements
    3. Save checkpoint every batch

    Args:
        client: LLM client with achat() method.
        plan: Stage 1 Call 2 plan.
        paper_id: Paper identifier.
        signals: All signal stubs from Pass 1.
        parsed_text: Full paper text (for a/b/c slicing).
        work_dir: If provided, save checkpoint periodically.
        existing_details: If provided (resume), skip already-done signals.

    Returns:
        Tuple of (list of SignalDetail, total_latency_ms).
    """
    done_names = {d.name for d in existing_details} if existing_details else set()
    remaining = [s for s in signals if s.name not in done_names]
    details: dict[str, SignalDetail] = {d.name: d for d in (existing_details or [])}
    total_latency = sum(d.latency_ms for d in details.values())

    if not remaining:
        return list(details.values()), total_latency

    # Load prompt
    system_text, user_template, params = _load_prompt(prompt_file)
    tmpl = _jinja_env.from_string(user_template)
    default_max = int(params.get("max_tokens", 5500))
    max_tokens = max(
        default_max,
        int(plan.token_budget.get("track_b_pass2_per_factor", default_max)),
    )

    # Initialize multi-turn session
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_text},
    ]
    supplement_count: dict[str, int] = {s.name: 0 for s in remaining}
    pending = {s.name: s for s in remaining}
    n_rounds = 0

    logger.info(
        "[track_b] paper=%s pass2: adaptive multi-turn starting "
        "(batch_size=%d, %d signals, max_rounds=%d)",
        paper_id, PASS2_BATCH_SIZE, len(remaining), PASS2_MAX_TOTAL_ROUNDS,
    )

    while pending and n_rounds < PASS2_MAX_TOTAL_ROUNDS:
        n_rounds += 1

        # Take next batch
        batch = list(pending.values())[:PASS2_BATCH_SIZE]
        user_msg = _render_user_msg(tmpl, paper_id, n_rounds, batch, parsed_text)
        messages.append({"role": "user", "content": user_msg})

        # Trim history if too long
        max_keep = 1 + PASS2_MAX_HISTORY_MESSAGES  # system + N pairs
        if len(messages) > max_keep:
            # Keep system (idx 0) and most recent (max_keep - 1) messages
            messages = [messages[0]] + messages[-(max_keep - 1):]
            logger.debug(
                "[track_b] paper=%s pass2 round %d: trimmed history to %d messages",
                paper_id, n_rounds, len(messages),
            )

        # LLM call
        t0 = time.monotonic()
        try:
            response = await client.achat(
                messages, max_tokens=max_tokens, temperature=0.1,
            )
        except DeferError:
            raise
        except Exception as exc:
            # All signals in batch failed
            for sig in batch:
                details[sig.name] = SignalDetail(
                    name=sig.name, success=False,
                    error=f"llm_error: {exc}",
                )
                pending.pop(sig.name, None)
            continue
        latency_ms = int((time.monotonic() - t0) * 1000)
        total_latency += latency_ms

        messages.append({"role": "assistant", "content": response})

        # Parse response
        parsed = _extract_json(response)
        factors = _unwrap_factors(parsed)

        if factors is None:
            # Parse failed: log and continue
            logger.warning(
                "[track_b] paper=%s pass2 round %d: JSON parse failed, retrying next round",
                paper_id, n_rounds,
            )
            continue

        # Match factors to batch
        if len(factors) != len(batch):
            logger.warning(
                "[track_b] paper=%s pass2 round %d: got %d factors for %d signals",
                paper_id, n_rounds, len(factors), len(batch),
            )
            # Pad/truncate to match
            if len(factors) < len(batch):
                # Missing: mark as failed
                for i in range(len(factors), len(batch)):
                    sig = batch[i]
                    if sig.name not in details:
                        details[sig.name] = SignalDetail(
                            name=sig.name, success=False,
                            error="missing_in_response",
                            latency_ms=latency_ms,
                        )
                        pending.pop(sig.name, None)
                factors = list(factors) + [{}] * (len(batch) - len(factors))
            else:
                factors = factors[:len(batch)]

        # Process each signal
        need_supplement: list[tuple[SignalStub, dict]] = []
        completed_count = 0
        for sig, factor in zip(batch, factors, strict=False):
            if not isinstance(factor, dict):
                continue
            need_info = factor.get("need_more_context")
            l1 = factor.get("l1")
            # Signal is "completed" only if l1 is filled (not null)
            is_completed = l1 is not None and isinstance(l1, dict) and l1

            if need_info and not is_completed:
                # LLM requests more context
                supplement_count.setdefault(sig.name, 0)
                if supplement_count[sig.name] < PASS2_MAX_SUPPLEMENTS_PER_SIGNAL:
                    supplement_count[sig.name] += 1
                    need_supplement.append((sig, need_info))
                    continue
                else:
                    # Max supplements reached, mark as failed
                    details[sig.name] = SignalDetail(
                        name=sig.name, success=False,
                        error="max_supplements_exceeded",
                        latency_ms=latency_ms,
                    )
                    pending.pop(sig.name, None)
                    continue
            elif is_completed:
                # Completed
                details[sig.name] = _build_signal_detail(sig, factor, latency_ms)
                pending.pop(sig.name, None)
                completed_count += 1
            else:
                # Neither completed nor need_more: probably JSON structure issue
                # Try to extract whatever is there
                if any(factor.get(k) for k in ("l1", "l2", "l3", "l4")):
                    details[sig.name] = _build_signal_detail(sig, factor, latency_ms)
                    pending.pop(sig.name, None)
                    completed_count += 1
                else:
                    details[sig.name] = SignalDetail(
                        name=sig.name, success=False,
                        error="no_l1_l2_l3_l4",
                        latency_ms=latency_ms,
                    )
                    pending.pop(sig.name, None)

        logger.info(
            "[track_b] paper=%s pass2 round %d: %d/%d completed, %d need supplements (%dms)",
            paper_id, n_rounds, completed_count, len(batch), len(need_supplement), latency_ms,
        )

        # Save checkpoint periodically
        if work_dir and n_rounds % 5 == 0:
            current_details = [details[s.name] for s in signals if s.name in details]
            _save_checkpoint(
                work_dir, paper_id,
                list(signals),
                current_details,
            )

        # Send supplemental context if needed
        if need_supplement:
            supplement_msg = _render_supplement_msg(need_supplement, parsed_text)
            messages.append({"role": "user", "content": supplement_msg})
            # LLM will re-process in next iteration

    # Mark any still-pending as failed
    for sig_name, _sig in pending.items():
        if sig_name not in details:
            details[sig_name] = SignalDetail(
                name=sig_name, success=False,
                error="max_total_rounds_exceeded",
            )

    # Final checkpoint
    if work_dir:
        current_details = [details[s.name] for s in signals if s.name in details]
        _save_checkpoint(work_dir, paper_id, list(signals), current_details)

    # Build final list (preserving original signal order)
    final = []
    for sig in signals:
        if sig.name in details:
            final.append(details[sig.name])
        else:
            final.append(SignalDetail(name=sig.name, success=False, error="not_processed"))

    logger.info(
        "[track_b] paper=%s pass2 adaptive done: %d rounds, %d/%d succeeded (success_rate=%.1f%%)",
        paper_id, n_rounds,
        sum(1 for d in final if d.success),
        len(final),
        100 * sum(1 for d in final if d.success) / len(final) if final else 0,
    )
    return final, total_latency


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
    retry_rounds = 0
    pass2_concurrency_used = 1
    if run_pass2:
        # Choose execution mode (v3: smart auto-select based on complexity)
        mode = select_pass2_mode(pass1_signals)
        if mode == "hybrid":
            logger.info(
                "[track_b] paper=%s pass2 mode: HYBRID (parallel + adaptive supplement, v3.1)",
                paper_id,
            )
            pass2_details, pass2_latency = _hybrid_pass2(
                client, plan, paper_id, pass1_signals, parsed_text,
                work_dir=work_dir,
                existing_details=pass2_details_done or None,
            )
            pass2_concurrency_used = PASS2_MAX_CONCURRENCY
        elif mode == "adaptive":
            logger.info(
                "[track_b] paper=%s pass2 mode: ADAPTIVE multi-turn (v2)",
                paper_id,
            )
            pass2_details, pass2_latency = asyncio.run(
                _run_pass2_adaptive(
                    client, plan, paper_id, pass1_signals, parsed_text,
                    work_dir=work_dir,
                    existing_details=pass2_details_done or None,
                )
            )
            pass2_concurrency_used = PASS2_BATCH_SIZE
        elif mode == "parallel":
            logger.info(
                "[track_b] paper=%s pass2 mode: PARALLEL (3-way, v1)",
                paper_id,
            )
            pass2_details, pass2_latency = asyncio.run(
                _run_pass2_parallel(
                    client, plan, paper_id, pass1_signals, parsed_text,
                    work_dir=work_dir,
                    existing_details=pass2_details_done or None,
                )
            )
            pass2_concurrency_used = PASS2_MAX_CONCURRENCY
        else:  # "serial"
            logger.info(
                "[track_b] paper=%s pass2 mode: SERIAL (v1)",
                paper_id,
            )
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
    success_rate = n_complete / len(pass2_details) if pass2_details else 0.0

    # Auto-retry logic for failed factors
    needs_retry = False
    if run_pass2 and success_rate < PASS2_SUCCESS_THRESHOLD_HIGH and n_failed > 0:
        if retry_rounds < PASS2_MAX_RETRY_ROUNDS:
            needs_retry = True
            # Get failed signal stubs
            failed_names = {d.name for d in pass2_details if not d.success}
            failed_stubs = [s for s in pass1_signals if s.name in failed_names]

            if failed_stubs:
                logger.info(
                    "[track_b] paper=%s retry: %d failed factors (success_rate=%.1f%%), retrying...",
                    paper_id, len(failed_stubs), success_rate * 100,
                )
                retry_rounds += 1

                # Retry failed factors
                if PASS2_USE_PARALLEL:
                    retry_details, retry_latency = asyncio.run(
                        _run_pass2_parallel(
                            client, plan, paper_id, failed_stubs, parsed_text,
                        )
                    )
                else:
                    retry_details, retry_latency = _run_pass2_serial(
                        client, plan, paper_id, failed_stubs, parsed_text,
                    )

                pass2_latency += retry_latency
                n_calls += len(retry_details)

                # Merge results: keep successful from original, replace failed with retry results
                successful_original = [d for d in pass2_details if d.success]
                pass2_details = successful_original + retry_details

                # Recalculate stats
                n_complete = sum(1 for d in pass2_details if d.success)
                n_failed = len(pass2_details) - n_complete
                success_rate = n_complete / len(pass2_details) if pass2_details else 0.0

                logger.info(
                    "[track_b] paper=%s retry result: %d/%d complete (%.1f%%)",
                    paper_id, n_complete, len(pass2_details), success_rate * 100,
                )

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
        pass2_concurrency=pass2_concurrency_used,
        total_latency_ms=total_latency,
        llm_calls=n_calls,
        success=True,
        success_rate=success_rate,
        retry_rounds=retry_rounds,
        needs_retry=success_rate < PASS2_SUCCESS_THRESHOLD_HIGH and not needs_retry,
    )
