"""``reproduce`` command — paper reproduction pipeline (Stage 0/1 + Track A/B).

Subcommands:
  llmwikify reproduce <paper>       — process a single PDF
  llmwikify reproduce batch <dir>   — batch process all PDFs in a directory

Outputs go to ``{wiki_root}/quant/papers/{paper_id}/``:
  - parsed.md       (Stage 0)
  - plan.json       (Stage 1)
  - track_a.json    (Track A tier-1 + tier-2)
  - track_b_pass1.json
  - track_b_pass2.json
  - preview.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import (
    print_error,
    print_info,
    print_json,
    print_success,
    print_warning,
    stderr_print,
)


def _slugify(name: str) -> str:
    """Convert paper filename to safe paper_id (matches orchestrator)."""
    s = Path(name).stem
    s = s.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return s[:200]


def run_one_paper_cli(args: Any, wiki_root: Path) -> int:
    """Run paper reproduction for a single PDF.

    Args:
        args: Parsed args with ``source`` (PDF path), ``paper_id`` (optional),
            ``no_pass2``, ``output`` (quant/papers root).
        wiki_root: Wiki root path.

    Returns:
        0 on success, 1 on failure.
    """
    from llmwikify.reproduction.llm_extraction import run_one_paper

    source = Path(args.source)
    if not source.exists():
        print_error(f"Source not found: {source}")
        return 1

    paper_id = getattr(args, "paper_id", None) or _slugify(source.name)
    output_root = Path(args.output) if getattr(args, "output", None) else (
        wiki_root / "quant" / "papers"
    )
    run_pass2 = not getattr(args, "no_pass2", False)

    stderr_print(f"=== Reproduce: {paper_id} ===")
    stderr_print(f"  Source: {source}")
    stderr_print(f"  Output: {output_root / paper_id}/")
    stderr_print(f"  Run Pass 2: {run_pass2}\n")

    t0 = time.monotonic()
    try:
        result = run_one_paper(
            paper_id=paper_id,
            source_path=source,
            output_root=output_root,
            run_pass2=run_pass2,
        )
    except Exception as exc:
        print_error(f"Failed: {exc}")
        return 1
    elapsed = (time.monotonic() - t0) / 60

    result["elapsed_min"] = round(elapsed, 2)
    result["paper_id"] = paper_id

    if getattr(args, "json", False):
        print_json(result)
    else:
        # Human-readable summary
        if result.get("success"):
            print_success(f"Done in {elapsed:.1f} min")
            print(f"  Signals: {result.get('n_signals', 0)}")
            print(f"  Pass 2 complete: {result.get('n_pass2_complete', 0)}/{result.get('n_pass2_complete', 0) + result.get('n_pass2_failed', 0)}")
            print(f"  LLM calls: {result.get('llm_calls', 0)}")
        else:
            print_warning(f"Completed with errors in {elapsed:.1f} min")
            print(f"  Error: {result.get('error', 'unknown')}")
            print(f"  Signals: {result.get('n_signals', 0)}")

    return 0 if result.get("success") else 1


def run_batch(args: Any, wiki_root: Path) -> int:
    """Batch process PDFs in a directory.

    Args:
        args: Parsed args with ``source`` (PDF dir), ``limit``, ``workers``,
            ``output``, ``no_pass2``.
        wiki_root: Wiki root path.

    Returns:
        0 on success, 1 if any paper failed.
    """
    from llmwikify.reproduction.llm_extraction import run_one_paper

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print_error(f"Not a directory: {source_dir}")
        return 1

    # Find all PDFs (recursive)
    pdfs = sorted([
        p for p in source_dir.rglob("*.pdf")
        if p.is_file() and not p.name.startswith(".")
    ])
    if getattr(args, "limit", 0):
        pdfs = pdfs[: args.limit]

    if not pdfs:
        print_error(f"No PDFs found in {source_dir}")
        return 1

    output_root = Path(args.output) if getattr(args, "output", None) else (
        wiki_root / "quant" / "papers"
    )
    workers = max(1, getattr(args, "workers", 1))
    run_pass2 = not getattr(args, "no_pass2", False)
    skip_existing = getattr(args, "skip_existing", True)

    stderr_print("=== Batch Reproduce ===")
    stderr_print(f"  Source: {source_dir}")
    stderr_print(f"  PDFs found: {len(pdfs)}")
    stderr_print(f"  Output: {output_root}/")
    stderr_print(f"  Workers: {workers}")
    stderr_print(f"  Run Pass 2: {run_pass2}")
    stderr_print(f"  Skip existing: {skip_existing}\n")

    if getattr(args, "dry_run", False):
        stderr_print("[DRY RUN] Would process:")
        for pdf in pdfs:
            paper_id = _slugify(pdf.name)
            work_dir = output_root / paper_id
            exists = (work_dir / "preview.md").exists()
            status = "skip" if exists and skip_existing else "process"
            stderr_print(f"  [{status}] {pdf.name} → {paper_id}/")
        return 0

    success_count = 0
    failed_count = 0
    skipped_count = 0
    batch_results = []
    t0 = time.monotonic()

    def process_one(pdf: Path) -> dict:
        paper_id = _slugify(pdf.name)
        work_dir = output_root / paper_id
        if skip_existing and (work_dir / "preview.md").exists():
            return {
                "paper_id": paper_id,
                "source": str(pdf),
                "status": "skipped",
                "reason": "preview.md exists",
            }
        try:
            t_paper = time.monotonic()
            result = run_one_paper(
                paper_id=paper_id,
                source_path=pdf,
                output_root=output_root,
                run_pass2=run_pass2,
            )
            result["elapsed_min"] = round((time.monotonic() - t_paper) / 60, 2)
            result["source"] = str(pdf)
            result["status"] = "success" if result.get("success") else "failed"
            return result
        except Exception as exc:
            return {
                "paper_id": paper_id,
                "source": str(pdf),
                "status": "error",
                "error": str(exc),
            }

    if workers == 1:
        # Sequential
        for i, pdf in enumerate(pdfs, 1):
            stderr_print(f"[{i}/{len(pdfs)}] {pdf.name}")
            result = process_one(pdf)
            status = result.get("status", "error")
            if status == "success":
                success_count += 1
                print_success_stderr_safe(
                    f"  ✓ {result.get('paper_id')}: {result.get('n_signals', 0)} signals "
                    f"({result.get('elapsed_min', 0):.1f} min)"
                )
            elif status == "skipped":
                skipped_count += 1
                print_info_stderr_safe("  ⊙ skipped (exists)")
            else:
                failed_count += 1
                print_error_stderr_safe(f"  ✗ {result.get('error', 'unknown')}")
            batch_results.append(result)
    else:
        # Parallel (ThreadPoolExecutor, not asyncio — orchestrator handles own loop)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_one, pdf): pdf for pdf in pdfs}
            for future in as_completed(futures):
                result = future.result()
                status = result.get("status", "error")
                if status == "success":
                    success_count += 1
                    print_success_stderr_safe(
                        f"  ✓ {result.get('paper_id')}: "
                        f"{result.get('n_signals', 0)} signals"
                    )
                elif status == "skipped":
                    skipped_count += 1
                else:
                    failed_count += 1
                    print_error_stderr_safe(
                        f"  ✗ {result.get('paper_id', '?')}: {result.get('error', 'unknown')}"
                    )
                batch_results.append(result)

    total_elapsed = (time.monotonic() - t0) / 60
    summary = {
        "batch_summary": {
            "total": len(pdfs),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "total_elapsed_min": round(total_elapsed, 2),
        },
        "results": batch_results,
    }

    if getattr(args, "json", False):
        print_json(summary)
    else:
        stderr_print(f"\n=== Batch Complete ({total_elapsed:.1f} min) ===")
        stderr_print(f"  Success: {success_count}, Failed: {failed_count}, Skipped: {skipped_count}")

    return 0 if failed_count == 0 else 1


def print_success_stderr_safe(msg: str) -> None:
    """Print success message to stderr (safe wrapper)."""
    try:
        from .._output import print_success_stderr
        print_success_stderr(msg)
    except ImportError:
        print(msg, file=sys.stderr)


def print_error_stderr_safe(msg: str) -> None:
    """Print error message to stderr (safe wrapper)."""
    try:
        from .._output import print_error_stderr
        print_error_stderr(msg)
    except ImportError:
        print(msg, file=sys.stderr)


def print_info_stderr_safe(msg: str) -> None:
    """Print info message to stderr (safe wrapper)."""
    try:
        from .._output import print_info_stderr
        print_info_stderr(msg)
    except ImportError:
        print(msg, file=sys.stderr)


class ReproduceCommand(Command):
    """``reproduce`` command — paper reproduction (Stage 0/1 + Track A/B).

    Subcommands:
      <paper>       — process a single PDF
      batch <dir>   — batch process all PDFs in a directory

    Output structure (per paper):
      {wiki_root}/quant/papers/{paper_id}/
        ├── parsed.md
        ├── plan.json
        ├── track_a.json
        ├── track_b_pass1.json
        ├── track_b_pass2.json
        ├── preview.md
        └── deferred.json (if any deferred items)

    Pass 2 modes (auto-selected via smart_mode):
      - parallel: 3 concurrent signals (default, fast)
      - adaptive: multi-turn with LLM self-assessment (deep)
      - hybrid:   parallel + supplement 20% shallow (best of both)

    See docs/summaries/pipeline_optimization_summary.md for details.
    """

    name = "reproduce"
    help = "Paper reproduction pipeline (Stage 0/1 + Track A/B)"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        # Add subparsers for subcommands
        sub = p.add_subparsers(dest="reproduce_action")

        # Single paper
        single = sub.add_parser("single", help="Process a single PDF")
        single.add_argument("source", help="PDF file path")
        single.add_argument("--paper-id", help="Override paper ID (default: filename)")
        single.add_argument("--no-pass2", action="store_true", help="Skip Pass 2 (only Stage 0/1)")
        single.add_argument("--output", "-o", help="Output root (default: {wiki_root}/quant/papers)")
        single.add_argument("--json", action="store_true", help="Output JSON to stdout")

        # Batch
        batch_p = sub.add_parser("batch", help="Batch process PDFs in a directory")
        batch_p.add_argument("source", help="Directory containing PDFs")
        batch_p.add_argument("--limit", "-l", type=int, default=0, help="Limit number of PDFs")
        batch_p.add_argument("--workers", "-w", type=int, default=1, help="Concurrent workers (1=sequential)")
        batch_p.add_argument("--no-pass2", action="store_true", help="Skip Pass 2")
        batch_p.add_argument("--output", "-o", help="Output root (default: {wiki_root}/quant/papers)")
        batch_p.add_argument("--skip-existing", action="store_true", default=True, help="Skip papers with existing preview.md (default: True)")
        batch_p.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="Re-process existing papers")
        batch_p.add_argument("--dry-run", "-n", action="store_true", help="Preview without processing")
        batch_p.add_argument("--json", action="store_true", help="Output JSON to stdout")

        # Backward compat: if no subcommand, treat first arg as source (single mode)
        p.add_argument("source_pos", nargs="?", help=argparse.SUPPRESS)
        p.add_argument("--paper-id", help=argparse.SUPPRESS)
        p.add_argument("--no-pass2", action="store_true", help=argparse.SUPPRESS)
        p.add_argument("--output", "-o", help=argparse.SUPPRESS)
        p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        wiki_root = wiki.root if hasattr(wiki, "root") else Path(wiki)

        # Determine action
        action = getattr(args, "reproduce_action", None)
        if action == "single":
            return run_one_paper_cli(args, wiki_root)
        elif action == "batch":
            return run_batch(args, wiki_root)
        elif getattr(args, "source_pos", None):
            # Backward compat: llmwikify reproduce <file>
            # Re-route to single mode
            args.source = args.source_pos
            return run_one_paper_cli(args, wiki_root)
        else:
            print_error("Usage: llmwikify reproduce {single|batch} ...")
            print("  llmwikify reproduce single <file.pdf>")
            print("  llmwikify reproduce batch <dir/>")
            return 1
