"""批量跑多个论文验证 hybrid 通用性.

选 5 个不同类型 PDF（不含 101 alphas 和广发，已单独测试）：
1. 招商证券-信贷周期论
2. 招商证券-科技三年上行周期
3. 浙商证券-政策框架
4. 招商证券-盈利韧性
5. 招商证券-A股投资三段论
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/home/ll/llmwikify")
sys.path.insert(0, str(ROOT / "src"))

from llmwikify.reproduction.llm_extraction import run_one_paper
from llmwikify.reproduction.llm_extraction.track_b import (
    PROMPT_PASS2_SUPPLEMENT,
    _assess_factor_quality,
    select_pass2_mode,
)

WORK_DIR_ROOT = ROOT / "quant/papers"

PDFS = [
    "/home/ll/Public/strategy/raw/20180302-招商证券-A股涅槃论（捌）：中国信贷周期论与机器进化论.pdf",
    "/home/ll/Public/strategy/raw/20180816-招商证券-A股投资启示录（一）：布局科技三年上行周期.pdf",
    "/home/ll/Public/strategy/raw/20181125-浙商证券-A股行业比较周报：政策框架的梳理和当前市场的分析.pdf",
    "/home/ll/Public/strategy/raw/20180823-招商证券-A股投资启示录（二）：盈利韧性，剩者为王与赢家通吃.pdf",
    "/home/ll/Public/strategy/raw/20180913-招商证券-A股投资启示录（三）：A股投资三段论，兼论市场底部信号与市场风格.pdf",
]


def _slugify(name: str) -> str:
    return Path(name).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")[:200]


def calc_stats(details):
    l3_int, l3_theo, l4_hyp = [], [], []
    success_count = 0
    for d in details:
        if not d.get("success"):
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


def main():
    """Run all PDFs sequentially with hybrid mode."""
    print("=" * 80)
    print("Hybrid Mode Generalization Test - 5 Papers")
    print("=" * 80)

    overall = {
        "total_papers": len(PDFS),
        "total_time_min": 0,
        "total_signals": 0,
        "total_pass2_success": 0,
        "papers": [],
    }

    for pdf_path in PDFS:
        pdf = Path(pdf_path)
        if not pdf.exists():
            print(f"\n[SKIP] {pdf.name} (not found)")
            continue

        paper_id = _slugify(pdf.name)
        work_dir = WORK_DIR_ROOT / paper_id
        if (work_dir / "preview.md").exists():
            print(f"\n[SKIP] {paper_id} (preview.md exists)")
            continue

        print(f"\n[{len(overall['papers']) + 1}/{len(PDFS)}] Processing: {pdf.name}")
        print(f"  paper_id: {paper_id}")
        print(f"  work_dir: {work_dir}")

        t0 = time.monotonic()
        try:
            result = run_one_paper(
                paper_id=paper_id,
                source_path=pdf,
                output_root=WORK_DIR_ROOT,
                run_pass2=True,
            )
        except Exception as exc:
            print(f"  [ERROR] {exc}")
            overall["papers"].append({
                "paper_id": paper_id,
                "error": str(exc),
                "status": "error",
            })
            continue
        elapsed = (time.monotonic() - t0) / 60

        print(f"  Elapsed: {elapsed:.1f} min")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Signals: {result.get('n_signals', 0)}")
        print(f"  Pass 2: {result.get('n_pass2_complete', 0)}/{result.get('n_pass2_complete', 0) + result.get('n_pass2_failed', 0)}")

        # Read pass2 details if exists
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

        overall["total_time_min"] += elapsed
        overall["total_signals"] += result.get("n_signals", 0)
        overall["total_pass2_success"] += result.get("n_pass2_complete", 0)
        overall["papers"].append({
            "paper_id": paper_id,
            "status": result.get("status", "success" if result.get("success") else "failed"),
            "elapsed_min": round(elapsed, 2),
            "n_signals": result.get("n_signals", 0),
            "n_pass2_complete": result.get("n_pass2_complete", 0),
            "n_pass2_failed": result.get("n_pass2_failed", 0),
            "stats": stats,
        })
        print(f"  Stats: l3.intuition={stats['avg_intuition']:.0f}, "
              f"l3.theoretical={stats['avg_theoretical']:.0f}, "
              f"hyp={stats['avg_hypotheses']:.1f}")

    # Save
    summary_path = ROOT / "quant/papers/hybrid_generalization_summary.json"
    summary_path.write_text(json.dumps(overall, indent=2, ensure_ascii=False))
    print(f"\n{'='*80}")
    print(f"Saved summary: {summary_path}")
    print(f"Total time: {overall['total_time_min']:.1f} min")
    print(f"Total signals: {overall['total_signals']}")
    print(f"Total pass2 success: {overall['total_pass2_success']}")


if __name__ == "__main__":
    main()