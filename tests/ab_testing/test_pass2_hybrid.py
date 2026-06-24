"""A/B test: Hybrid Pass 2 vs Parallel Pass 2.

Compares:
- v3.0 Parallel (existing): 33.7 min, l3.intuition=105 chars
- v3.1 Hybrid (new): parallel + adaptive supplement for shallow 20%

Usage:
    PASS2_MODE_OVERRIDE=hybrid python tests/ab_testing/test_pass2_hybrid.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Add src to path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.llm_factory import build_default_client
from llmwikify.reproduction.paper_understanding.llm_extraction.planner import plan_paper
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    _hybrid_pass2,
    _assess_factor_quality,
    HYBRID_SUPPLEMENT_RATIO,
    select_pass2_mode,
)
from llmwikify.reproduction.paper_understanding.llm_extraction.stage0_ingest import parse_paper
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    SignalDetail, _run_pass2_parallel,
)


PAPER_ID = "1601.00991v3_hybrid"
WORK_DIR = ROOT / "quant" / "papers" / "101_alphas_hybrid"
WORK_DIR.mkdir(parents=True, exist_ok=True)


def load_parsed() -> str:
    """Load existing parsed text from v3.0 run."""
    p = ROOT / "quant/papers/101_alphas_v3/parsed.md"
    return p.read_text()


def load_pass1_signals():
    """Load Pass 1 signals from v3.0 run."""
    p = ROOT / "quant/papers/101_alphas_v3/track_b_pass1.json"
    data = json.loads(p.read_text())
    # Reconstruct SignalStub-like objects (dicts, since SignalStub is a dataclass)
    return data["pass1_signals"]


def main():
    """Run hybrid mode on 101 alphas."""
    print("=" * 70)
    print("Hybrid Pass 2 A/B Test")
    print("=" * 70)

    parsed_text = load_parsed()
    pass1_signals_dict = load_pass1_signals()
    print(f"Loaded {len(pass1_signals_dict)} signals")

    # Build plan
    plan = build_plan(
        paper_id=PAPER_ID,
        parsed_text=parsed_text,
        schema_choice="factor",
    )

    # Build LLM client
    client = build_default_client()

    # Convert dicts to SignalStub-like objects (use dict directly - hybrid accepts list)
    # _hybrid_pass2 expects list[SignalStub], but SignalStub is a dataclass
    # For test purposes, the parallel function uses .name, .formula_brief, .context_excerpt
    # So we need actual SignalStub instances
    from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import SignalStub
    signals = []
    for i, d in enumerate(pass1_signals_dict):
        signals.append(SignalStub(
            index=i,
            name=d["name"],
            formula_brief=d.get("formula_brief", ""),
            description=d.get("description", ""),
            context_excerpt=d.get("context_excerpt", ""),
            context_start=d.get("context_start", 0),
            context_end=d.get("context_end", 0),
        ))

    print(f"Reconstructed {len(signals)} SignalStub instances")
    mode = select_pass2_mode(signals)
    print(f"Auto-selected mode: {mode}")

    t0 = time.monotonic()

    if mode == "hybrid":
        print("Running hybrid mode...")
        details, latency = _hybrid_pass2(
            client, plan, PAPER_ID, signals, parsed_text,
            work_dir=WORK_DIR,
        )
    else:
        print(f"Mode {mode} not hybrid, running parallel for comparison...")
        details, latency = asyncio.run(
            _run_pass2_parallel(client, plan, PAPER_ID, signals, parsed_text)
        )

    elapsed = (time.monotonic() - t0) / 60
    print(f"\nTotal time: {elapsed:.1f} min, Latency: {latency}ms")

    # Assess
    n_complete = sum(1 for d in details if d.success)
    n_failed = len(details) - n_complete

    l3_intuitions = []
    l3_theoreticals = []
    l4_hypothesis_counts = []
    for d in details:
        if d.success:
            l3 = d.l3 or {}
            intuition = str(l3.get("financial_intuition", "") or l3.get("intuition", "") or "")
            theoretical = str(l3.get("theoretical_basis", "") or "")
            l3_intuitions.append(len(intuition))
            l3_theoreticals.append(len(theoretical))
            hyp = (d.l4 or {}).get("hypotheses", []) or []
            l4_hypothesis_counts.append(len(hyp) if isinstance(hyp, list) else 0)

    avg_intuition = sum(l3_intuitions) / len(l3_intuitions) if l3_intuitions else 0
    avg_theoretical = sum(l3_theoreticals) / len(l3_theoreticals) if l3_theoreticals else 0
    avg_hyp = sum(l4_hypothesis_counts) / len(l4_hypothesis_counts) if l4_hypothesis_counts else 0

    summary = {
        "paper_id": PAPER_ID,
        "mode": mode,
        "n_signals": len(details),
        "n_complete": n_complete,
        "n_failed": n_failed,
        "elapsed_min": round(elapsed, 2),
        "latency_ms": latency,
        "l3_avg_intuition_chars": round(avg_intuition, 1),
        "l3_avg_theoretical_chars": round(avg_theoretical, 1),
        "l4_avg_hypotheses": round(avg_hyp, 2),
        "success_rate": round(n_complete / len(details), 4) if details else 0,
    }
    print(f"\nSummary:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Save summary
    summary_path = WORK_DIR / "ab_summary_hybrid.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSaved to {summary_path}")

    # Compare with v3.0 parallel
    v3_summary_path = ROOT / "quant/papers/101_alphas_v3/ab_summary_v3.json"
    if v3_summary_path.exists():
        v3 = json.loads(v3_summary_path.read_text())
        print(f"\n📊 vs v3.0 Parallel:")
        print(f"  Time: {v3.get('elapsed_min', 'N/A')} → {summary['elapsed_min']} min")
        print(f"  l3.intuition: {v3.get('l3_avg_intuition_chars', 'N/A')} → {summary['l3_avg_intuition_chars']} chars")
        print(f"  Success: {v3.get('success_rate', 'N/A')} → {summary['success_rate']}")


if __name__ == "__main__":
    main()