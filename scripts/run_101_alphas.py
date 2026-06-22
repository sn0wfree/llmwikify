"""Run all 101 alphas in batch mode and produce a summary.

Reuses ``run_one_factor`` from ``test_one_factor_llm_code.py`` (ReAct
self-repair + QuantNodes PipelineRunner).

Usage:
  python scripts/run_101_alphas.py                  # run all
  python scripts/run_101_alphas.py --start 1 --end 5  # run 1..5
  python scripts/run_101_alphas.py --skip-existing   # skip already-done files
  python scripts/run_101_alphas.py --max-failures 5  # stop after 5 failures

Output:
  scripts/output/multi_alpha_001_to_101.json
  scripts/output/multi_alpha_summary.md  (human-readable table)
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

# Ensure the parent dir is importable
sys.path.insert(0, str(Path(__file__).parent))

from test_one_factor_llm_code import run_one_factor


class _AlphaTimeout(Exception):
    """Raised when an alpha run exceeds the per-alpha timeout."""
    pass


def _alarm_handler(signum, frame):
    raise _AlphaTimeout("alpha run exceeded timeout")


def _run_with_timeout(idx: int, timeout_sec: int) -> dict:
    """Run a single alpha with a hard timeout via SIGALRM.

    On timeout, returns a failure dict instead of hanging the whole batch.
    """
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout_sec)
    t0 = time.monotonic()
    try:
        result = run_one_factor(idx, use_react=True)
        return result
    except _AlphaTimeout:
        return {
            "status": "failed",
            "stage": "timeout",
            "error": f"Alpha {idx} exceeded {timeout_sec}s timeout",
            "elapsed_sec": time.monotonic() - t0,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "stage": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": time.monotonic() - t0,
        }
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

OUTPUT_DIR = Path("/home/ll/llmwikify/scripts/output")
TRACK_B = Path("/home/ll/llmwikify/quant/papers/101_alphas_minimal/track_b_checkpoint.json")


def _load_formula_briefs() -> list[dict]:
    """Load all alpha records from track_b_checkpoint.json."""
    data = json.loads(TRACK_B.read_text(encoding="utf-8"))
    return data["pass1_signals"]


def _print_header() -> None:
    print("=" * 100)
    print("  101-Alpha Batch Runner")
    print("=" * 100)


def _print_row(idx: int, result: dict, elapsed_cum: float) -> None:
    status = result.get("status", "unknown")
    ic = result.get("ic_mean")
    icir = result.get("icir")
    wr = result.get("ic_winrate")
    elapsed = result.get("elapsed_sec", 0)

    ic_str = f"{ic:+.4f}" if isinstance(ic, (int, float)) and ic == ic else "  NaN"
    icir_str = f"{icir:+.4f}" if isinstance(icir, (int, float)) and icir == icir else "  NaN"
    wr_str = f"{wr * 100:5.1f}%" if isinstance(wr, (int, float)) and wr == wr else "  NaN"
    note = result.get("stage", "") if status != "success" else ""

    print(f"  {idx:>3}  {status:<8} {ic_str:>10} {icir_str:>10} {wr_str:>8}  {elapsed:>6.1f}s  {note}")


def _print_summary(results: list[dict]) -> None:
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]

    ic_means = [r["ic_mean"] for r in success if r.get("ic_mean") is not None and r["ic_mean"] == r["ic_mean"]]
    icirs = [r["icir"] for r in success if r.get("icir") is not None and r["icir"] == r["icir"]]
    winrates = [r["ic_winrate"] for r in success if r.get("ic_winrate") is not None and r["ic_winrate"] == r["ic_winrate"]]

    avg_ic = sum(ic_means) / len(ic_means) if ic_means else None
    avg_icir = sum(icirs) / len(icirs) if icirs else None
    avg_wr = sum(winrates) / len(winrates) if winrates else None

    print("\n" + "=" * 100)
    print("  Summary")
    print("=" * 100)
    print(f"  Total:  {len(results)}  |  Success: {len(success)}  |  Failed: {len(failed)}")
    if ic_means:
        print(f"  Avg IC: {avg_ic:+.4f}  |  Avg ICIR: {avg_icir:+.4f}  |  Avg Winrate: {(avg_wr or 0) * 100:.1f}%")
    if failed:
        print("\n  Failed alphas:")
        for r in failed:
            idx = r.get("alpha_index")
            idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            print(f"    alpha-{idx_s}: {r.get('stage', '?')} - {r.get('error', '?')[:80]}")
    print("=" * 100)


def _write_json(results: list[dict], path: Path) -> None:
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    ic_means = [r["ic_mean"] for r in success if r.get("ic_mean") is not None and r["ic_mean"] == r["ic_mean"]]
    icirs = [r["icir"] for r in success if r.get("icir") is not None and r["icir"] == r["icir"]]
    winrates = [r["ic_winrate"] for r in success if r.get("ic_winrate") is not None and r["ic_winrate"] == r["ic_winrate"]]

    summary = {
        "total": len(results),
        "success_count": len(success),
        "failed_count": len(failed),
        "aggregate": {
            "ic_mean_avg": round(sum(ic_means) / len(ic_means), 4) if ic_means else None,
            "icir_avg": round(sum(icirs) / len(icirs), 4) if icirs else None,
            "winrate_avg": round(sum(winrates) / len(winrates), 4) if winrates else None,
        },
        "alphas": [
            {
                "index": r.get("alpha_index"),
                "status": r.get("status"),
                "ic_mean": r.get("ic_mean"),
                "icir": r.get("icir"),
                "ic_winrate": r.get("ic_winrate"),
                "code_chars": r.get("code_chars"),
                "elapsed_sec": r.get("elapsed_sec"),
                "stage": r.get("stage", ""),
                "error": r.get("error", "")[:200],
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _write_markdown(results: list[dict], path: Path) -> None:
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    ic_means = [r["ic_mean"] for r in success if r.get("ic_mean") is not None and r["ic_mean"] == r["ic_mean"]]
    icirs = [r["icir"] for r in success if r.get("icir") is not None and r["icir"] == r["icir"]]
    winrates = [r["ic_winrate"] for r in success if r.get("ic_winrate") is not None and r["ic_winrate"] == r["ic_winrate"]]

    lines = [
        "# 101-Alpha Batch Results",
        "",
        f"- Total: {len(results)} | Success: {len(success)} | Failed: {len(failed)}",
    ]
    if ic_means:
        avg_ic = sum(ic_means) / len(ic_means)
        avg_icir = sum(icirs) / len(icirs)
        avg_wr = sum(winrates) / len(winrates)
        lines.append(f"- Avg IC: {avg_ic:+.4f} | Avg ICIR: {avg_icir:+.4f} | Avg Winrate: {avg_wr * 100:.1f}%")
    lines += [
        "",
        "| Alpha | Status | IC | ICIR | Winrate | Code | Elapsed |",
        "|-------|--------|----|------|---------|------|---------|",
    ]
    for r in results:
        idx = r.get("alpha_index")
        st = r.get("status", "?")
        ic = r.get("ic_mean")
        icir = r.get("icir")
        wr = r.get("ic_winrate")
        ic_s = f"{ic:+.4f}" if isinstance(ic, float) and ic == ic else "NaN"
        icir_s = f"{icir:+.4f}" if isinstance(icir, float) and icir == icir else "NaN"
        wr_s = f"{wr * 100:.1f}%" if isinstance(wr, float) and wr == wr else "NaN"
        cc = r.get("code_chars", 0) or 0
        el = r.get("elapsed_sec", 0) or 0
        idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
        lines.append(f"| alpha-{idx_s} | {st} | {ic_s} | {icir_s} | {wr_s} | {cc} | {el:.1f}s |")

    if failed:
        lines += ["", "## Failed Alphas", ""]
        for r in failed:
            idx = r.get("alpha_index")
            idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            lines.append(f"- alpha-{idx_s}: `{r.get('stage', '?')}` - {r.get('error', '?')[:100]}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_llm_extract(args: argparse.Namespace) -> None:
    """Phase 3: extract L2-L6 metadata from existing single_factor_NNN.json files.

    Uses factor_extractor.extract_batch (3 concurrent LLM calls, ~60s/alpha).
    Skips alphas without JSON (no LLM code re-run needed).
    """
    from llmwikify.reproduction.factor_extractor import extract_batch

    indices = list(range(args.start, args.end + 1))
    print("=" * 80)
    print("  Phase 3: LLM Extract L2-L6 Metadata")
    print("=" * 80)
    print(f"  Indices: {args.start}-{args.end}")
    print(f"  Output dir: {OUTPUT_DIR}")
    print()

    # Filter: only alphas with existing single_factor_NNN.json
    available = [i for i in indices if (OUTPUT_DIR / f"single_factor_{i:03d}.json").exists()]
    if not available:
        print("  [error] no single_factor_NNN.json found in output/")
        print("  Run Phase 1 first (without --llm-extract)")
        return
    print(f"  Available: {len(available)} alphas with JSON ({available[:5]}...)")
    print()

    # L5 hypothesis via run_l5_pipeline (optional, adds ~5min)
    print("  [info] L5 hypothesis_testing skipped (requires FastAPI server)")
    print("  [info] To enable: start server, then POST /api/factor/{slug}/validate")
    print()

    results = extract_batch(available, output_dir=OUTPUT_DIR, max_workers=3)

    # Summary
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    print()
    print("=" * 80)
    print(f"  Phase 3 complete: {len(success)}/{len(results)} success")
    if failed:
        print("  Failed:")
        for r in failed:
            print(f"    alpha-{r['alpha_index']:03d}: {r.get('error', '?')[:80]}")
    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch run 101 alphas")
    parser.add_argument("--start", type=int, default=1, help="First alpha index (default: 1)")
    parser.add_argument("--end", type=int, default=101, help="Last alpha index (default: 101)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip alphas that already have output JSON")
    parser.add_argument("--max-failures", type=int, default=999, help="Stop after N failures (default: unlimited)")
    parser.add_argument("--rounds", type=int, default=3, help="Max ReAct repair rounds (default: 3)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds to sleep between alpha runs (default: 3.0)")
    parser.add_argument("--no-delay", action="store_true", help="Disable inter-alpha delay (for testing only)")
    parser.add_argument("--timeout", type=int, default=180, help="Per-alpha timeout in seconds (default: 180)")
    parser.add_argument("--llm-extract", action="store_true", help="Phase 3: LLM extract L2-L6 metadata (reads existing JSONs, no LLM code re-run)")
    args = parser.parse_args()

    # Phase 3: LLM extraction mode (fast, no LLM code re-run)
    if args.llm_extract:
        _run_llm_extract(args)
        return

    _print_header()
    t0 = time.monotonic()

    # Optionally skip already-done alphas
    skip: set[int] = set()
    if args.skip_existing:
        for idx in range(args.start, args.end + 1):
            p = OUTPUT_DIR / f"single_factor_{idx:03d}.json"
            if p.exists():
                skip.add(idx)
        if skip:
            print(f"  [skip] {len(skip)} alphas already done: {sorted(skip)[:10]}...")

    results: list[dict] = []
    failures: int = 0

    for idx in range(args.start, args.end + 1):
        if idx in skip:
            # Load existing result
            p = OUTPUT_DIR / f"single_factor_{idx:03d}.json"
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if "alpha_index" not in loaded:
                loaded["alpha_index"] = idx
            results.append(loaded)
            continue

        elapsed_cum = time.monotonic() - t0
        print(f"\n[{time.strftime('%H:%M:%S')}] alpha-{idx:03d} (elapsed: {elapsed_cum:.0f}s, failures: {failures})")

        result = run_one_factor(idx, use_react=True)
        # Inject alpha_index if missing (run_one_factor omits it on failure)
        if "alpha_index" not in result:
            result["alpha_index"] = idx
        results.append(result)

        _print_row(idx, result, elapsed_cum)

        # Save individual result
        out_file = OUTPUT_DIR / f"single_factor_{idx:03d}.json"
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        if result.get("status") != "success":
            failures += 1
            if failures >= args.max_failures:
                print(f"\n[stop] {failures} failures reached --max-failures={args.max_failures}")
                break

        # Sleep between runs to avoid 429 rate limiting
        if idx < args.end and args.delay > 0 and not args.no_delay:
            time.sleep(args.delay)

    # Write summary files
    _write_json(results, OUTPUT_DIR / "multi_alpha_001_to_101.json")
    _write_markdown(results, OUTPUT_DIR / "multi_alpha_summary.md")
    _print_summary(results)

    total_elapsed = time.monotonic() - t0
    print(f"\n  Total elapsed: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print(f"  Results saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
