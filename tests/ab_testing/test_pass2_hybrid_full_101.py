"""完整 101 alphas hybrid A/B 测试.

Phase 1: 复用 v3.0 parallel 结果（已有数据）
Phase 2: supplement top 20 shallow signals with PROMPT_PASS2_SUPPLEMENT
Merge: 用 supplement 替换 shallow 后的 parallel 结果
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path("/home/ll/llmwikify")
sys.path.insert(0, str(ROOT / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.llm_factory import (
    build_default_client,
)

from llmwikify.reproduction.paper_understanding.llm_extraction.planner import plan_paper
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    PROMPT_PASS2_SUPPLEMENT,
    SignalDetail,
    SignalStub,
    _assess_factor_quality,
    _run_pass2_adaptive,
    _select_supplement_targets,
)

PAPER_ID = "101_alphas_hybrid_full"
WORK_DIR = ROOT / "quant" / "papers" / PAPER_ID
WORK_DIR.mkdir(parents=True, exist_ok=True)

parsed_text = (ROOT / "quant/papers/101_alphas_v3/parsed.md").read_text()
p1 = json.loads((ROOT / "quant/papers/101_alphas_v3/track_b_pass1.json").read_text())
p2 = json.loads((ROOT / "quant/papers/101_alphas_v3/track_b_pass2.json").read_text())

# Reconstruct SignalStub list
all_stubs = [
    SignalStub(
        index=d.get("index", i),
        name=d["name"],
        formula_brief=d.get("formula_brief", ""),
        description=d.get("description", ""),
        context_excerpt=d.get("context_excerpt", ""),
        context_start=d.get("context_start", 0),
        context_end=d.get("context_end", 0),
    ) for i, d in enumerate(p1["pass1_signals"])
]
print(f"Total signals: {len(all_stubs)}")

# Reconstruct parallel details
parallel_details = [
    SignalDetail(
        name=d["name"],
        description=d.get("description", ""),
        l1=d.get("l1", {}),
        l2=d.get("l2", {}),
        l3=d.get("l3", {}),
        l4=d.get("l4", {}),
        success=d.get("success", True),
        latency_ms=d.get("latency_ms", 0),
    ) for d in p2["pass2_details"] if d is not None
]
print(f"Parallel details: {len(parallel_details)}")

# Select supplement targets (20% of 101 = ~20, min 3)
supplement_stubs, supplement_details = _select_supplement_targets(
    parallel_details, all_stubs, parsed_text
)
print(f"Supplement targets: {len(supplement_stubs)}")
print(f"  Names: {[s.name for s in supplement_stubs]}")

# Plan + client
plan = plan_paper(paper_id=PAPER_ID, title="101 Formulaic Alphas", parsed_text=parsed_text)
client = build_default_client()

# Run supplement phase with PROMPT_PASS2_SUPPLEMENT
print("\nRunning supplement with PROMPT_PASS2_SUPPLEMENT...")
t0 = time.monotonic()
supplement_results, sup_latency = asyncio.run(
    _run_pass2_adaptive(
        client, plan, PAPER_ID, supplement_stubs, parsed_text,
        prompt_file=PROMPT_PASS2_SUPPLEMENT,
    )
)
sup_elapsed = (time.monotonic() - t0) / 60
print(f"\nSupplement complete in {sup_elapsed:.2f} min")

# Merge: replace parallel details with supplement results for matched names
final_details = []
supplement_names = {s.name for s in supplement_stubs}
sup_by_name = {d.name: d for d in supplement_results if d.success}

replaced = 0
for d in parallel_details:
    if d.name in supplement_names:
        replacement = sup_by_name.get(d.name)
        if replacement:
            final_details.append(replacement)
            replaced += 1
        else:
            final_details.append(d)
    else:
        final_details.append(d)

# Stats
print(f"\nFinal: {len(final_details)} details, {replaced} replaced")

l3_int = []
l3_theo = []
l4_hyp = []
for d in final_details:
    if not d.success:
        continue
    l3 = d.l3 or {}
    int_str = str(l3.get("financial_intuition", "") or l3.get("intuition", "") or "")
    theo_str = str(l3.get("theoretical_basis", "") or "")
    hyp = (d.l4 or {}).get("hypotheses", []) or []
    l3_int.append(len(int_str))
    l3_theo.append(len(theo_str))
    l4_hyp.append(len(hyp) if isinstance(hyp, list) else 0)

avg_int = sum(l3_int)/len(l3_int) if l3_int else 0
avg_theo = sum(l3_theo)/len(l3_theo) if l3_theo else 0
avg_hyp = sum(l4_hyp)/len(l4_hyp) if l4_hyp else 0

print("\n📊 Hybrid final stats:")
print(f"  l3.intuition avg: {avg_int:.1f} chars")
print(f"  l3.theoretical avg: {avg_theo:.1f} chars")
print(f"  l4.hypotheses avg: {avg_hyp:.2f}")

# Per-target comparison
print("\nPer-target depth change:")
for name in [s.name for s in supplement_stubs]:
    v3 = next((d for d in parallel_details if d.name == name), None)
    final = next((d for d in final_details if d.name == name), None)
    if not v3 or not final:
        continue
    v3_l3 = v3.l3 or {}
    v3_int = str(v3_l3.get("financial_intuition", "") or v3_l3.get("intuition", "") or "")
    v3_theo = str(v3_l3.get("theoretical_basis", "") or "")
    v3_hyp = len((v3.l4 or {}).get("hypotheses", []) or [])
    final_l3 = final.l3 or {}
    final_int = str(final_l3.get("financial_intuition", "") or final_l3.get("intuition", "") or "")
    final_theo = str(final_l3.get("theoretical_basis", "") or "")
    final_hyp = len((final.l4 or {}).get("hypotheses", []) or [])
    print(f"  {name}: int={len(v3_int)}→{len(final_int)} ({len(final_int)-len(v3_int):+d}), "
          f"theo={len(v3_theo)}→{len(final_theo)} ({len(final_theo)-len(v3_theo):+d}), "
          f"hyp={v3_hyp}→{final_hyp}")

summary = {
    "paper_id": PAPER_ID,
    "mode": "hybrid_with_supplement",
    "n_total_signals": len(all_stubs),
    "n_parallel": len(parallel_details),
    "n_supplemented": replaced,
    "supplement_latency_ms": sup_latency,
    "supplement_elapsed_min": round(sup_elapsed, 2),
    "l3_avg_intuition_chars": round(avg_int, 1),
    "l3_avg_theoretical_chars": round(avg_theo, 1),
    "l4_avg_hypotheses": round(avg_hyp, 2),
    "n_complete": sum(1 for d in final_details if d.success),
    "n_failed": sum(1 for d in final_details if not d.success),
    "success_rate": round(sum(1 for d in final_details if d.success) / len(final_details), 4) if final_details else 0,
}
(WORK_DIR / "ab_summary_hybrid_full.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False)
)
print(f"\nSaved: {WORK_DIR}/ab_summary_hybrid_full.json")

# Save final details
(WORK_DIR / "track_b_pass2_hybrid.json").write_text(
    json.dumps({
        "paper_id": PAPER_ID,
        "mode": "hybrid_with_supplement",
        "pass2_details": [
            {
                "name": d.name, "description": d.description,
                "l1": d.l1, "l2": d.l2, "l3": d.l3, "l4": d.l4,
                "success": d.success, "latency_ms": d.latency_ms,
                "error": d.error,
            }
            for d in final_details
        ],
    }, indent=2, ensure_ascii=False)
)
print(f"Saved final details: {WORK_DIR}/track_b_pass2_hybrid.json")
