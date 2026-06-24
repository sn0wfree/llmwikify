"""Hybrid vs Parallel A/B Generalization Test.

在 5 个不同 paper 上跑 parallel + hybrid 两次，输出 A/B 对比。

每个 paper 输出到两个目录：
- <id>_parallel/ (PASS2_MODE_OVERRIDE=parallel)
- <id>_hybrid/ (PASS2_MODE_OVERRIDE=hybrid)

计算每个 mode 的 stats，对比 delta：
- l3.intuition chars
- l3.theoretical chars
- l4.hypotheses count
- pass2 success rate
- 耗时

输出：
- quant/papers/hybrid_ab_summary.json (机器可读)
- docs/summaries/hybrid_ab_results.md (人类可读，由 Stage A3 生成)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path("/home/ll/llmwikify")
sys.path.insert(0, str(ROOT / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper

WORK_DIR_ROOT = ROOT / "quant/papers"

PDFS = [
    # (path, schema_hint)  schema_hint 仅用于报告, 实际从 plan 取
    ("/home/ll/Public/strategy/raw/20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论.pdf", "signal"),
    ("/home/ll/Public/strategy/raw/20180816-招商证券-A股投资启示录（一）：布局科技三年上行周期.pdf", "allocation"),
    ("/home/ll/Public/strategy/raw/20181125-浙商证券-A股行业比较周报：政策框架的梳理和当前市场的分析.pdf", "summary"),
    ("/home/ll/Public/strategy/raw/20180823-招商证券-A股投资启示录（二）：盈利韧性，剩者为王与赢家通吃.pdf", "allocation"),
    ("/home/ll/Public/strategy/raw/20180913-招商证券-A股投资启示录（三）：A股投资三段论，兼论市场底部信号与市场风格.pdf", "factor"),
]


def _slugify(name: str) -> str:
    return Path(name).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")[:200]


def calc_stats(details: list[dict]) -> dict:
    """Calculate aggregate stats for a list of SignalDetail dicts."""
    l3_int, l3_theo, l4_hyp = [], [], []
    success_count = 0
    for d in details:
        if not d or not d.get("success"):
            continue
        success_count += 1
        l3 = d.get("l3", {}) or {}
        int_str = str(l3.get("financial_intuition", "") or l3.get("intuition", "") or "")
        theo_str = str(l3.get("theoretical_basis", "") or "")
        hyp = (d.get("l4", {}) or {}).get("hypotheses", []) or []
        l3_int.append(len(int_str))
        l3_theo.append(len(theo_str))
        l4_hyp.append(len(hyp) if isinstance(hyp, list) else 0)
    return {
        "n_total": len(details),
        "n_success": success_count,
        "avg_intuition": sum(l3_int)/len(l3_int) if l3_int else 0,
        "avg_theoretical": sum(l3_theo)/len(l3_theo) if l3_theo else 0,
        "avg_hypotheses": sum(l4_hyp)/len(l4_hyp) if l4_hyp else 0,
    }


def run_paper_in_mode(pdf_path: Path, paper_id: str, mode: str) -> dict:
    """Run a paper in given mode ('parallel' or 'hybrid'). Returns stats dict."""
    work_dir = WORK_DIR_ROOT / paper_id
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    env_key = "PASS2_MODE_OVERRIDE"
    os.environ[env_key] = mode

    print(f"\n  [{mode.upper()}] {paper_id}")
    print(f"  work_dir: {work_dir}")

    t0 = time.monotonic()
    try:
        result = run_one_paper(
            paper_id=paper_id,
            source_path=pdf_path,
            output_root=WORK_DIR_ROOT,
            run_pass2=True,
        )
    except Exception as exc:
        print(f"  [ERROR] {exc}")
        return {
            "mode": mode,
            "paper_id": paper_id,
            "error": str(exc),
            "status": "error",
        }
    elapsed = (time.monotonic() - t0) / 60

    n_signals = result.get("n_signals", 0)
    n_complete = result.get("n_pass2_complete", 0)
    n_failed = result.get("n_pass2_failed", 0)
    success_rate = n_complete / (n_complete + n_failed) if (n_complete + n_failed) > 0 else 0

    print(f"  [{mode.upper()}] Done in {elapsed:.1f} min, "
          f"signals={n_signals}, pass2={n_complete}/{n_complete + n_failed} "
          f"({success_rate*100:.1f}%)")

    pass2_path = work_dir / "track_b_pass2.json"
    stats = {"n_total": 0, "n_success": 0, "avg_intuition": 0,
             "avg_theoretical": 0, "avg_hypotheses": 0}
    if pass2_path.exists():
        try:
            p2 = json.loads(pass2_path.read_text())
            details = p2.get("pass2_details", [])
            stats = calc_stats([d for d in details if d])
        except Exception as exc:
            print(f"  [WARN] Cannot read pass2: {exc}")

    print(f"  [{mode.upper()}] Stats: l3.int={stats['avg_intuition']:.0f}, "
          f"l3.theo={stats['avg_theoretical']:.0f}, "
          f"hyp={stats['avg_hypotheses']:.1f}")

    return {
        "mode": mode,
        "paper_id": paper_id,
        "status": result.get("status", "success" if result.get("success") else "failed"),
        "elapsed_min": round(elapsed, 2),
        "n_signals": n_signals,
        "n_pass2_complete": n_complete,
        "n_pass2_failed": n_failed,
        "success_rate": round(success_rate, 4),
        "stats": stats,
    }


def run_paper_ab(pdf_path: Path, schema_hint: str) -> dict:
    """Run a paper in both parallel and hybrid modes, return A/B comparison."""
    pdf = Path(pdf_path)
    base_id = _slugify(pdf.name)
    parallel_id = f"{base_id}_ab_parallel"
    hybrid_id = f"{base_id}_ab_hybrid"

    print(f"\n{'='*80}")
    print(f"Paper: {pdf.name}")
    print(f"  schema_hint: {schema_hint}")
    print(f"{'='*80}")

    parallel_result = run_paper_in_mode(pdf, parallel_id, "parallel")
    hybrid_result = run_paper_in_mode(pdf, hybrid_id, "hybrid")

    return {
        "paper_id": base_id,
        "pdf": pdf.name,
        "schema_hint": schema_hint,
        "parallel": parallel_result,
        "hybrid": hybrid_result,
    }


def main():
    print("=" * 80)
    print("Hybrid vs Parallel A/B Generalization Test - 5 Papers")
    print("=" * 80)

    overall = {
        "total_papers": len(PDFS),
        "total_time_min": 0,
        "papers": [],
    }

    t_start = time.monotonic()

    for pdf_path, schema_hint in PDFS:
        pdf = Path(pdf_path)
        if not pdf.exists():
            print(f"\n[SKIP] {pdf.name} (not found)")
            continue

        result = run_paper_ab(pdf, schema_hint)
        overall["papers"].append(result)

    overall["total_time_min"] = round((time.monotonic() - t_start) / 60, 2)

    # Save summary
    summary_path = ROOT / "quant/papers/hybrid_ab_summary.json"
    summary_path.write_text(json.dumps(overall, indent=2, ensure_ascii=False))
    print(f"\n{'='*80}")
    print(f"Saved summary: {summary_path}")
    print(f"Total time: {overall['total_time_min']} min")

    # Print comparison table
    print(f"\n{'='*80}")
    print("A/B Comparison Summary")
    print(f"{'='*80}")
    print(f"{'Paper':<60} {'Mode':<10} {'l3.int':<8} {'l3.theo':<8} {'hyp':<6} {'time':<8}")
    print("-" * 100)
    for r in overall["papers"]:
        base = r["paper_id"][:58]
        for mode_key in ("parallel", "hybrid"):
            m = r[mode_key]
            if "error" in m:
                continue
            s = m["stats"]
            print(f"{base:<60} {mode_key:<10} {s['avg_intuition']:<8.0f} {s['avg_theoretical']:<8.0f} {s['avg_hypotheses']:<6.1f} {m['elapsed_min']:<8.1f}")


if __name__ == "__main__":
    main()
