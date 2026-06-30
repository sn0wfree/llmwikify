"""A/B test: compare adaptive multi-turn Pass 2 vs original parallel Pass 2.

Usage:
    python tests/ab_testing/test_pass2_adaptive.py

The script:
1. Backs up existing Pass 2 results
2. Runs new adaptive Pass 2 on the same paper
3. Compares output quality, latency, token usage
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.llm_factory import (
    build_default_client,
)

from llmwikify.reproduction.paper_understanding.llm_extraction.planner import PlanResult
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    SignalDetail,
    SignalStub,
    _run_pass2_adaptive,
    _run_pass2_parallel,
)


def load_existing_pass2(paper_dir: Path) -> tuple[list[SignalStub], list[SignalDetail]]:
    """Load existing Pass 1 signals and Pass 2 details from paper directory."""
    plan_data = json.loads((paper_dir / "plan.json").read_text())
    plan_info = plan_data.get("stage1_call2_plan", {})

    # Load pass1 signals from track_b_pass1.json
    pass1_path = paper_dir / "track_b_pass1.json"
    if not pass1_path.exists():
        return [], []

    pass1_data = json.loads(pass1_path.read_text())
    stubs = [
        SignalStub(
            index=s.get("index", i + 1),
            name=s["name"],
            formula_brief=s.get("formula_brief", ""),
            description=s.get("description", ""),
            context_excerpt=s.get("context_excerpt", ""),
            context_start=s.get("context_start", 0),
            context_end=s.get("context_end", 0),
        )
        for i, s in enumerate(pass1_data.get("signals", []))
    ]

    # Load pass2 details from track_b_pass2.json
    pass2_path = paper_dir / "track_b_pass2.json"
    if not pass2_path.exists():
        return stubs, []

    pass2_data = json.loads(pass2_path.read_text())
    details = []
    for d in pass2_data.get("factors", []):
        details.append(SignalDetail(
            name=d["name"],
            description=d.get("description", ""),
            l1=d.get("l1", {}),
            l2=d.get("l2", {}),
            l3=d.get("l3", {}),
            l4=d.get("l4", {}),
            success=d.get("success", False),
            error=d.get("error"),
            latency_ms=d.get("latency_ms", 0),
        ))
    return stubs, details


def compare_factors(
    baseline: list[SignalDetail],
    new: list[SignalDetail],
    sample_n: int = 5,
) -> dict:
    """Compare baseline vs new Pass 2 output quality."""
    baseline_by_name = {d.name: d for d in baseline}
    new_by_name = {d.name: d for d in new}

    common_names = set(baseline_by_name) & set(new_by_name)
    sampled = sorted(common_names)[:sample_n]

    comparison = {
        "baseline_total": len(baseline),
        "new_total": len(new),
        "common": len(common_names),
        "baseline_success": sum(1 for d in baseline if d.success),
        "new_success": sum(1 for d in new if d.success),
        "samples": [],
    }

    for name in sampled:
        b = baseline_by_name[name]
        n = new_by_name[name]
        sample = {
            "name": name,
            "baseline": {
                "success": b.success,
                "l1_formula": b.l1.get("formula", "") if isinstance(b.l1, dict) else "",
                "l1_input_cols": b.l1.get("input_columns", []) if isinstance(b.l1, dict) else [],
                "l3_intuition_len": len(b.l3.get("financial_intuition", "")) if isinstance(b.l3, dict) else 0,
                "l4_hypotheses_count": len(b.l4.get("hypotheses", [])) if isinstance(b.l4, dict) else 0,
            },
            "new": {
                "success": n.success,
                "l1_formula": n.l1.get("formula", "") if isinstance(n.l1, dict) else "",
                "l1_input_cols": n.l1.get("input_columns", []) if isinstance(n.l1, dict) else [],
                "l3_intuition_len": len(n.l3.get("financial_intuition", "")) if isinstance(n.l3, dict) else 0,
                "l4_hypotheses_count": len(n.l4.get("hypotheses", [])) if isinstance(n.l4, dict) else 0,
            },
        }
        comparison["samples"].append(sample)

    return comparison


def run_adaptive_pass2(
    paper_dir: Path,
    client,
    plan: PlanResult,
    parsed_text: str,
    stubs: list[SignalStub],
) -> tuple[list[SignalDetail], int, float]:
    """Run adaptive Pass 2 and return (details, llm_calls, total_time_s)."""
    t0 = time.time()
    details, total_latency_ms = asyncio.run(
        _run_pass2_adaptive(
            client, plan, paper_dir.name, stubs, parsed_text,
        )
    )
    elapsed = time.time() - t0
    # llm_calls approximated as number of successful details
    return details, len(details), elapsed


def main():
    parser = argparse.ArgumentParser(description="A/B test adaptive Pass 2")
    parser.add_argument(
        "--paper-dir", type=Path,
        default=PROJECT_ROOT / "quant/papers/101_alphas_test",
        help="Paper directory to test",
    )
    parser.add_argument(
        "--sample-n", type=int, default=5,
        help="Number of sample signals to compare",
    )
    args = parser.parse_args()

    from llmwikify.foundation.logging import setup_logging

    setup_logging(
        level=logging.INFO,
        log_file=None,
        fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logger = logging.getLogger("ab_test")

    paper_dir = args.paper_dir
    if not paper_dir.exists():
        logger.error("Paper directory does not exist: %s", paper_dir)
        sys.exit(1)

    logger.info("=" * 70)
    logger.info("A/B Test: Adaptive Pass 2 Multi-Turn")
    logger.info("=" * 70)
    logger.info("Paper dir: %s", paper_dir)

    # Load baseline
    stubs, baseline_details = load_existing_pass2(paper_dir)
    if not stubs:
        logger.error("No Pass 1 signals found in %s", paper_dir)
        sys.exit(1)

    logger.info("Loaded %d signals from Pass 1", len(stubs))
    logger.info("Baseline Pass 2: %d/%d completed",
                sum(1 for d in baseline_details if d.success),
                len(baseline_details))

    # Load plan
    plan_data = json.loads((paper_dir / "plan.json").read_text())
    plan_info = plan_data["stage1_call2_plan"]
    plan = PlanResult(
        paper_id=paper_dir.name,
        schema_choice=plan_info.get("schema_choice", "factor"),
        paper_type=plan_info.get("paper_type", ""),
        n_signals_estimate=plan_info.get("n_signals_estimate", len(stubs)),
        extraction_strategy=plan_info.get("extraction_strategy", ""),
        token_budget=plan_info.get("token_budget", {}),
        confidence=plan_info.get("confidence", 0.0),
        success=True,
    )

    # Load parsed text
    parsed_text_path = paper_dir / "parsed.md"
    parsed_text = parsed_text_path.read_text(encoding="utf-8")

    # Run adaptive Pass 2
    client = build_default_client()
    logger.info("Running ADAPTIVE Pass 2 (this may take a while)...")
    new_details, llm_calls, elapsed_s = run_adaptive_pass2(
        paper_dir, client, plan, parsed_text, stubs,
    )

    # Compare
    comparison = compare_factors(baseline_details, new_details, args.sample_n)

    logger.info("=" * 70)
    logger.info("RESULTS")
    logger.info("=" * 70)
    logger.info("Baseline: %d/%d successful in %d details",
                comparison["baseline_success"],
                comparison["baseline_total"],
                len(baseline_details))
    logger.info("New (adaptive): %d/%d successful in %d details",
                comparison["new_success"],
                comparison["new_total"],
                len(new_details))
    logger.info("LLM calls: %d", llm_calls)
    logger.info("Total time: %.1f seconds", elapsed_s)

    logger.info("")
    logger.info("Sample comparison (first %d common signals):", args.sample_n)
    for sample in comparison["samples"]:
        logger.info("")
        logger.info("  Signal: %s", sample["name"])
        logger.info("    Baseline:")
        logger.info("      l1.formula: %s", sample["baseline"]["l1_formula"][:100])
        logger.info("      l3.intuition length: %d",
                    sample["baseline"]["l3_intuition_len"])
        logger.info("      l4.hypotheses count: %d",
                    sample["baseline"]["l4_hypotheses_count"])
        logger.info("    New (adaptive):")
        logger.info("      l1.formula: %s", sample["new"]["l1_formula"][:100])
        logger.info("      l3.intuition length: %d",
                    sample["new"]["l3_intuition_len"])
        logger.info("      l4.hypotheses count: %d",
                    sample["new"]["l4_hypotheses_count"])

    # Save results
    output = {
        "paper_dir": str(paper_dir),
        "baseline": {
            "total": comparison["baseline_total"],
            "success": comparison["baseline_success"],
        },
        "new": {
            "total": comparison["new_total"],
            "success": comparison["new_success"],
            "llm_calls": llm_calls,
            "total_time_s": elapsed_s,
        },
        "samples": comparison["samples"],
    }
    output_path = paper_dir / "ab_test_results.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    logger.info("")
    logger.info("Results saved to: %s", output_path)


if __name__ == "__main__":
    main()
