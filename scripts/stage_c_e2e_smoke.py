"""阶段 C: 真实 LLM 跑 1-3 个 alpha 端到端验证 (e2e smoke test).

用法: python3 scripts/stage_c_e2e_smoke.py [N]
  - N = 1 (默认), 3, 5, 10
  - 跑 track_b_checkpoint.json 前 N 个 alpha
  - 调 FactorCompiler.compile() (真 LLM, 不 MOCK)
  - persist_l5_to_yaml 写 factor yaml
  - telemetry 收集 compile.start / success / failure / repair.*

输出:
  - quant/factors/stock/formulaic/alpha-001.yaml ... (含 l5.ast)
  - Telemetry summary 落盘: scripts/output/stage_c_e2e_N.json

注意:
  - 不要用 MOCK (那是编译链路测试, 不能验证真 LLM)
  - API throttle 时 sleep 1-2 秒
  - 跑完后 cat telemetry summary 看成功率 / repair 触发率
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

# Disable MOCK env
os.environ.pop("FACTOR_COMPILER_MOCK", None)


def build_factor_data(idx: int, name: str, formula_brief: str) -> dict:
    """Build minimal factor_data dict for FactorCompiler."""
    return {
        "name": f"alpha_{idx:03d}",
        "asset_type": "stock",
        "category": "formulaic",
        "source_paper": "101_alphas_minimal",
        "l1": {
            "definition": formula_brief[:200],
            "formula": formula_brief,
            "input_columns": ["open", "high", "low", "close", "volume", "returns", "vwap"],
            "default_params": {},
            "frequency": "日频",
            "output_schema": "[date × Code]",
            "nan_meaning": "TBD",
        },
        "l2": {
            "calculation_steps": [
                {"step": 1, "description": formula_brief[:200]}
            ],
            "edge_case_handling": "TBD",
            "missing_value_handling": "TBD",
            "data_alignment": "T+1",
            "complexity": "O(T × N)",
        },
        "l3": {
            "financial_intuition": "TBD",
            "market_behavior": "TBD",
            "theoretical_basis": "TBD",
            "historical_effectiveness": "TBD",
            "related_factors": [],
        },
        "l4": {
            "hypotheses": [],
            "hypothesis_limit": 5,
            "archived_hypotheses": [],
            "meaning_summary": "TBD",
            "key_insights": [],
            "uncertainty": "TBD",
            "final_meaning": None,
        },
        "l5": {
            "ast": None,
            "ast_compile_status": "pending",
            "overall_assessment": {"score": 0, "status": "未验证", "modules": {}},
        },
    }


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    track_b_path = ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json"
    with track_b_path.open(encoding="utf-8") as f:
        track_b = json.load(f)

    signals = track_b.get("pass1_signals", [])[:n]
    print(f"[stage_c] Running {len(signals)} alphas with real LLM...")
    print(f"[stage_c] track_b source: {track_b_path}")

    from llmwikify.reproduction.factor_compiler import FactorCompiler
    from llmwikify.reproduction.telemetry import get_telemetry

    telemetry = get_telemetry()
    telemetry.reset()
    compiler = FactorCompiler()
    results = []

    t_overall = time.monotonic()
    for sig in signals:
        idx = sig["index"]
        name = sig["name"]
        formula = sig["formula_brief"]
        factor_data = build_factor_data(idx, name, formula)

        t0 = time.monotonic()
        try:
            r = compiler.compile(factor_data, use_cache=False)
            elapsed = time.monotonic() - t0
            print(
                f"  [{idx:03d}] {name}: valid={r.is_valid}, "
                f"iters={r.iterations}, src={r.source}, "
                f"elapsed={elapsed:.1f}s",
            )
            if r.error_message:
                print(f"        err: {r.error_message[:100]}")
            results.append({
                "index": idx,
                "name": name,
                "valid": r.is_valid,
                "iterations": r.iterations,
                "source": r.source,
                "elapsed_sec": round(elapsed, 2),
                "error": (r.error_message or "")[:200],
            })
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  [{idx:03d}] {name}: CRASH ({exc})")
            results.append({
                "index": idx,
                "name": name,
                "valid": False,
                "iterations": 0,
                "source": "crash",
                "elapsed_sec": round(elapsed, 2),
                "error": str(exc)[:200],
            })
        # Light throttle avoid
        time.sleep(0.3)

    total = time.monotonic() - t_overall
    print(f"\n[stage_c] Total: {total:.1f}s")

    # Telemetry summary
    t_summary = telemetry.summary()
    print("\n[stage_c] Telemetry counts:")
    for event, count in sorted(t_summary["counts"].items()):
        print(f"  {event}: {count}")
    print(f"  total_events: {t_summary['total_events']}")

    success = t_summary["counts"].get("compile.success", 0)
    failure = t_summary["counts"].get("compile.failure", 0)
    repair_success = t_summary["counts"].get("repair.success", 0)
    yaml_persist = t_summary["counts"].get("yaml.l5.persist", 0)
    print(
        f"\n[stage_c] success_rate: {success / max(success + failure, 1):.1%}"
        f", repair_triggered: {repair_success}, yaml_persisted: {yaml_persist}",
    )

    # Save output
    out_dir = ROOT / "scripts" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"stage_c_e2e_{n}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "n_alphas": n,
            "total_elapsed_sec": round(total, 2),
            "results": results,
            "telemetry": t_summary,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[stage_c] Output: {out_path}")


if __name__ == "__main__":
    main()
