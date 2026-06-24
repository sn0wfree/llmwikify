"""广发论文完整流程: Stage 0 → 1 → Track B hybrid → factor YAML.

Pipeline:
1. Stage 0: parsed.md 已有
2. Stage 1: section detector + planner
3. Track B Pass 1: enumerate signals
4. Track B Pass 2: hybrid (parallel + supplement)

Output: YAML files for each factor + summary
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path("/home/ll/llmwikify")
sys.path.insert(0, str(ROOT / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.llm_factory import build_default_client
from llmwikify.reproduction.paper_understanding.llm_extraction.planner import plan_paper
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import (
    PROMPT_PASS2_SUPPLEMENT,
    SignalStub,
    _assess_factor_quality,
    _hybrid_pass2,
    _run_pass2_adaptive,
    select_pass2_mode,
)

# 广发论文
PAPER_DIR = ROOT / "quant/papers/20160803-天风证券-投资策略_从风格到配置_让分析框架告诉我们该配什么"
WORK_DIR = PAPER_DIR  # 直接写到同一目录
PAPER_TITLE = "天风证券-投资策略：从风格到配置，让分析框架告诉我们该配什么？"
PAPER_ID = "guangfa_20160803"

parsed_text = (PAPER_DIR / "parsed.md").read_text()
plan_data = json.loads((PAPER_DIR / "plan.json").read_text())
print(f"Loaded parsed text: {len(parsed_text)} chars")
print(f"Plan has sections: {len(plan_data.get('stage1_call1_sections', {}).get('sections', []))}")

client = build_default_client()

# Stage 1 Call 2: plan (already have, but run to confirm)
print("\n[Stage 1] Running planner...")
plan = plan_paper(
    paper_id=PAPER_ID,
    title=PAPER_TITLE,
    parsed_text=parsed_text,
)
print(f"  schema_choice: {plan.schema_choice}")
print(f"  token_budget: {plan.token_budget}")

if plan.schema_choice == "summary":
    print("Paper classified as 'summary' (not factor-based). Skip Track B.")
    sys.exit(0)

# Track B Pass 1
print("\n[Pass 1] Enumerating signals...")
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import _run_pass1
pass1_stubs, pass1_latency, n_calls = _run_pass1(
    client, plan, PAPER_ID, parsed_text,
)
print(f"  Found {len(pass1_stubs)} signals ({pass1_latency}ms)")

if not pass1_stubs:
    print("No signals found.")
    sys.exit(0)

# Save Pass 1
(PAPER_DIR / "track_b_pass1.json").write_text(json.dumps({
    "paper_id": PAPER_ID,
    "n_pass1": len(pass1_stubs),
    "n_signals": len(pass1_stubs),
    "pass1_signals": [s.to_dict() for s in pass1_stubs],
    "latency_ms": pass1_latency,
}, indent=2, ensure_ascii=False))

# Smart mode selection
mode = select_pass2_mode(pass1_stubs)
print(f"\n[Pass 2] Auto-selected mode: {mode}")

# Run Track B (which uses smart mode internally)
t0 = time.monotonic()
from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import run_track_b
result = run_track_b(
    paper_id=PAPER_ID,
    parsed_text=parsed_text,
    plan=plan,
    llm_client=client,
    work_dir=PAPER_DIR,
)
elapsed = (time.monotonic() - t0) / 60

print(f"\n[Pass 2] Complete in {elapsed:.2f} min")
print(f"  Pass 2 complete: {result.n_pass2_complete}")
print(f"  Pass 2 failed: {result.n_pass2_failed}")
print(f"  Success rate: {result.success_rate:.1%}")
print(f"  Concurrency: {result.pass2_concurrency}")

# Stats
l3_int = []
l3_theo = []
l4_hyp = []
for d in result.pass2_details:
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

summary = {
    "paper_id": PAPER_ID,
    "title": PAPER_TITLE,
    "mode": mode,
    "n_pass1_signals": len(pass1_stubs),
    "n_pass2_complete": result.n_pass2_complete,
    "n_pass2_failed": result.n_pass2_failed,
    "success_rate": round(result.success_rate, 4),
    "elapsed_min": round(elapsed, 2),
    "pass1_latency_ms": pass1_latency,
    "pass2_latency_ms": result.pass2_latency_ms,
    "l3_avg_intuition_chars": round(avg_int, 1),
    "l3_avg_theoretical_chars": round(avg_theo, 1),
    "l4_avg_hypotheses": round(avg_hyp, 2),
    "pass2_concurrency": result.pass2_concurrency,
}
(PAPER_DIR / "ab_summary_guangfa.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False)
)
print(f"\nSaved: {PAPER_DIR}/ab_summary_guangfa.json")
print(f"  l3.intuition avg: {avg_int:.1f} chars")
print(f"  l3.theoretical avg: {avg_theo:.1f} chars")
print(f"  l4.hypotheses avg: {avg_hyp:.2f}")