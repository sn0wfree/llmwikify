"""Generic paper reproduction runner — modular framework entry point.

PR7: uses the new modular framework (PR1-PR6) to reproduce any paper.
Reads `paper.yaml` config (or built-in defaults via --paper-id) and
builds a PaperRecipe, then runs the PaperPipeline.

Usage:
  python scripts/run_paper.py --paper-id 101_alphas_minimal
  python scripts/run_paper.py --paper-id 1601_00991v3 --smoke
  python scripts/run_paper.py --recipe quant/papers/my/paper.yaml
  python scripts/run_paper.py --paper-id 101_alphas_minimal --start 1 --end 5
  python scripts/run_paper.py --paper-id 101_alphas_minimal --skip-existing
  python scripts/run_paper.py --paper-id 101_alphas_minimal --no-delay --workers 3

Design: docs/designs/run_101_alphas_v2_design.md §17.16
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llmwikify.foundation.logging import setup_logging
from llmwikify.reproduction.backtest import QuantNodesBacktest
from llmwikify.reproduction.core import PaperPipeline, PaperRecipe
from llmwikify.reproduction.data_source.akshare_h5 import AkShareH5DataSource
from llmwikify.reproduction.reporting import BatchReporter
from llmwikify.reproduction.signal_source import (
    AcademicPdfSignalSource,
    TrackBPass2SignalSource,
    TrackBSignalSource,
)
from llmwikify.reproduction.sink import (
    BatchSummarySink,
    SingleJsonSink,
    YamlDuckdbSink,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("run_paper")


# ─── Paper registry (built-in defaults) ───────────────────────────────

@dataclass(slots=True)
class PaperDefaults:
    """Default config for a known paper (built-in)."""
    paper_id: str
    paper_dir: Path
    signal_source_type: str          # "track_b" / "track_b_pass2" / "academic_pdf"
    signal_source_path: Path         # path to track_b*.json
    output_dir: Path
    factors_dir: Path
    strategy_dir: str
    json_filename: str
    md_filename: str
    is_academic: bool = False        # True for academic papers (1601)


# Papers known to have data + track_b (or pass2) files
PAPER_REGISTRY: dict[str, PaperDefaults] = {
    "101_alphas_minimal": PaperDefaults(
        paper_id="101_alphas_minimal",
        paper_dir=PROJECT_ROOT / "quant" / "papers" / "101_alphas_minimal",
        signal_source_type="track_b",
        signal_source_path=PROJECT_ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json",
        output_dir=PROJECT_ROOT / "scripts" / "output",
        factors_dir=PROJECT_ROOT / "quant" / "factors",
        strategy_dir="101_alphas",
        json_filename="multi_alpha_001_to_101.json",
        md_filename="multi_alpha_summary.md",
    ),
    "1601_00991v3": PaperDefaults(
        paper_id="1601_00991v3",
        paper_dir=PROJECT_ROOT / "quant" / "papers" / "1601_00991v3",
        signal_source_type="academic_pdf",
        signal_source_path=PROJECT_ROOT / "quant" / "papers" / "1601_00991v3" / "track_b_pass2.json",
        output_dir=PROJECT_ROOT / "scripts" / "output" / "1601_00991v3",
        factors_dir=PROJECT_ROOT / "quant" / "factors" / "1601",
        strategy_dir="1601_alphas",
        json_filename="multi_alpha_1601_00991v3.json",
        md_filename="multi_alpha_1601_00991v3.md",
        is_academic=True,
    ),
}


def _resolve_broker_paper(paper_id: str) -> PaperDefaults | None:
    """Try to auto-resolve a broker paper by its paper_id (e.g. 招商/浙商)."""
    paper_dir = PROJECT_ROOT / "quant" / "papers" / paper_id
    if not paper_dir.exists():
        return None
    pass2_path = paper_dir / "track_b_pass2.json"
    if not pass2_path.exists():
        return None
    return PaperDefaults(
        paper_id=paper_id,
        paper_dir=paper_dir,
        signal_source_type="track_b_pass2",
        signal_source_path=pass2_path,
        output_dir=PROJECT_ROOT / "scripts" / "output" / paper_id,
        factors_dir=PROJECT_ROOT / "quant" / "factors" / paper_id,
        strategy_dir=paper_id,
        json_filename=f"multi_alpha_{paper_id}.json",
        md_filename=f"multi_alpha_{paper_id}.md",
    )


def get_paper_defaults(paper_id: str) -> PaperDefaults:
    """Resolve paper_id → PaperDefaults (built-in or auto-detected)."""
    if paper_id in PAPER_REGISTRY:
        return PAPER_REGISTRY[paper_id]
    # Try broker paper (招商/浙商 auto-detect)
    resolved = _resolve_broker_paper(paper_id)
    if resolved is not None:
        return resolved
    raise ValueError(
        f"Unknown paper_id: {paper_id!r}. "
        f"Either use a built-in id ({list(PAPER_REGISTRY)}) or pass --recipe <yaml>."
    )


# ─── SignalSource factory ─────────────────────────────────────────────


def build_signal_source(defaults: PaperDefaults):
    """Build a SignalSource from PaperDefaults."""
    if defaults.signal_source_type == "track_b":
        return TrackBSignalSource(defaults.signal_source_path, paper_id=defaults.paper_id)
    if defaults.signal_source_type == "track_b_pass2":
        return TrackBPass2SignalSource(defaults.signal_source_path, paper_id=defaults.paper_id)
    if defaults.signal_source_type == "academic_pdf":
        return AcademicPdfSignalSource(defaults.signal_source_path, paper_id=defaults.paper_id)
    raise ValueError(f"Unknown signal_source_type: {defaults.signal_source_type}")


# ─── Sinks factory ────────────────────────────────────────────────────


def build_sinks(defaults: PaperDefaults) -> list:
    """Build the 3 standard sinks (single JSON / YAML+DuckDB / batch summary)."""
    return [
        SingleJsonSink(output_dir=defaults.output_dir),
        YamlDuckdbSink(
            factors_dir=defaults.factors_dir,
            strategy_dir=defaults.strategy_dir,
        ),
        BatchSummarySink(
            output_dir=defaults.output_dir,
            paper_id=defaults.paper_id,
            json_filename=defaults.json_filename,
            md_filename=defaults.md_filename,
        ),
    ]


# ─── PaperRecipe factory ──────────────────────────────────────────────


def build_recipe(
    defaults: PaperDefaults,
    *,
    workers: int = 1,
    delay: float = 0.0,
    no_delay: bool = True,
    timeout: int = 180,
    skip_existing: bool = False,
    max_failures: int = 999,
) -> PaperRecipe:
    """Build a PaperRecipe from PaperDefaults + CLI overrides."""
    return PaperRecipe(
        paper_id=defaults.paper_id,
        signal_source=build_signal_source(defaults),
        data_source=AkShareH5DataSource(
            data_path=Path.home() / ".llmwikify" / "akshare_cache" / "quantnodes_h5_long",
        ),
        backtest_engine=QuantNodesBacktest(),
        sinks=build_sinks(defaults),
        reporter=BatchReporter,
        delay=0.0 if no_delay else delay,
        workers=min(workers, 3),
        timeout=timeout,
        skip_existing=skip_existing,
        max_failures=max_failures,
    )


# ─── Smoke mode (no LLM) ──────────────────────────────────────────────


def run_smoke(defaults: PaperDefaults) -> int:
    """Smoke test: verify SignalSource + paper data, no LLM calls.

    Returns 0 on success, 1 on failure.
    """
    logger.info("=== SMOKE TEST: %s ===", defaults.paper_id)
    logger.info("signal_source_type: %s", defaults.signal_source_type)
    logger.info("signal_source_path: %s", defaults.signal_source_path)

    if not defaults.signal_source_path.exists():
        logger.error("Signal source file not found: %s", defaults.signal_source_path)
        return 1

    src = build_signal_source(defaults)
    paper_id = src.paper_id
    logger.info("paper_id (resolved): %s", paper_id)

    signals = list(src.iter_signals())
    logger.info("signals found: %d", len(signals))

    if not signals:
        logger.error("No signals found — paper may not be fully processed")
        return 1

    # Sample first 3 signals
    for i, sig in enumerate(signals[:3]):
        logger.info(
            "  signal[%d]: id=%s name=%s formula_brief=%s",
            i, sig.id, sig.name, sig.formula_brief[:60],
        )

    # Verify output dirs exist or can be created
    for d in [defaults.output_dir, defaults.factors_dir]:
        d.mkdir(parents=True, exist_ok=True)
        logger.info("output_dir ready: %s", d)

    logger.info("=== SMOKE TEST PASSED ===")
    return 0


# ─── Main entry point ─────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run paper reproduction via modular framework (PR1-PR6).",
    )
    # Mode selection
    parser.add_argument("--paper-id", type=str, default=None,
                        help="Built-in paper id (101_alphas_minimal / 1601_00991v3 / broker paper dirs)")
    parser.add_argument("--recipe", type=Path, default=None,
                        help="Path to paper.yaml config (advanced usage)")

    # Smoke
    parser.add_argument("--smoke", action="store_true",
                        help="Smoke test only: verify SignalSource + paper data, no LLM")

    # 101-alphas style filtering
    parser.add_argument("--start", type=int, default=1, help="First alpha index (default: 1)")
    parser.add_argument("--end", type=int, default=None, help="Last alpha index (default: all)")

    # Pipeline
    parser.add_argument("--workers", type=int, default=1, help="Concurrent workers (default: 1, max: 3)")
    parser.add_argument("--delay", type=float, default=0.0, help="Inter-signal delay seconds (default: 0.0)")
    parser.add_argument("--no-delay", action="store_true", default=True,
                        help="Disable inter-signal delay (default: ON)")
    parser.add_argument("--timeout", type=int, default=180, help="Per-signal timeout seconds (default: 180)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip signals with existing result files")
    parser.add_argument("--max-failures", type=int, default=999, help="Stop after N failures")

    # Logging
    parser.add_argument("--log-file", type=Path, default=None, help="Log file path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    args = parser.parse_args()

    # Setup logging
    log_path: Path = args.log_file or PROJECT_ROOT / "scripts" / "output" / "run_paper.log"
    setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO,
        log_dir=log_path.parent,
        log_file=log_path.name,
        force=True,
    )
    logger.info("run_paper.py started (pid=%d)", __import__("os").getpid())

    # Resolve paper
    if args.recipe:
        logger.warning("--recipe mode not yet implemented in PR7 (use --paper-id)")
        return 1
    if not args.paper_id:
        parser.error("Either --paper-id or --recipe is required")
    try:
        defaults = get_paper_defaults(args.paper_id)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    # Smoke test (no LLM)
    if args.smoke:
        return run_smoke(defaults)

    # Build recipe + run pipeline
    recipe = build_recipe(
        defaults,
        workers=args.workers,
        delay=args.delay,
        no_delay=args.no_delay,
        timeout=args.timeout,
        skip_existing=args.skip_existing,
        max_failures=args.max_failures,
    )
    pipeline = PaperPipeline(recipe)

    # Compute indices (101-alphas style filtering)
    start = args.start
    end = args.end if args.end is not None else 9999
    if defaults.signal_source_type == "track_b":
        # 101 alphas: filter by index
        indices = range(start, end + 1)
        logger.info("Running paper_id=%s range=[%d, %d]", defaults.paper_id, start, end)
        results = pipeline.run(indices=indices)
    else:
        # 招商/1601: no index filter, run all signals
        logger.info("Running paper_id=%s (all signals, no index filter)", defaults.paper_id)
        results = pipeline.run()

    # Summary
    success = sum(1 for r in results if getattr(r, "status", None) == "success")
    failed = sum(1 for r in results if getattr(r, "status", None) != "success")
    logger.info("=== DONE: %d total, %d success, %d failed ===",
                len(results), success, failed)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
