"""Aggregate per-alpha E2E results into a single summary.

Reads scripts/output/single_factor_*.json (001..005) and produces:
  - scripts/output/multi_alpha_001_to_005_summary.json
  - prints a markdown comparison table

Usage: python3 scripts/aggregate_alpha_results.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

OUTPUT_DIR = Path("/home/ll/llmwikify/scripts/output")
ALPHA_INDICES = [1, 2, 3, 4, 5]
SUMMARY_PATH = OUTPUT_DIR / "multi_alpha_001_to_005_summary.json"


def _load(idx: int) -> dict | None:
    path = OUTPUT_DIR / f"single_factor_{idx:03d}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    alphas: list[dict] = []
    for idx in ALPHA_INDICES:
        data = _load(idx)
        if data is None:
            print(f"  [warn] single_factor_{idx:03d}.json missing, skipping")
            continue
        alphas.append(
            {
                "index": idx,
                "name": data.get("factor_name", f"alpha-{idx:03d}"),
                "formula_brief": data.get("formula_brief", ""),
                "status": data.get("status", "unknown"),
                "stage": data.get("stage", "-"),
                "ic_mean": data.get("ic_mean"),
                "icir": data.get("icir"),
                "ic_winrate": data.get("ic_winrate"),
                "code_chars": data.get("code_chars"),
                "factor_series_len": data.get("factor_series_len"),
                "elapsed_sec": data.get("elapsed_sec"),
            }
        )

    success = [a for a in alphas if a["status"] == "success"]
    ic_means = [a["ic_mean"] for a in success if a["ic_mean"] is not None and a["ic_mean"] == a["ic_mean"]]
    icirs = [a["icir"] for a in success if a["icir"] is not None and a["icir"] == a["icir"]]
    winrates = [a["ic_winrate"] for a in success if a["ic_winrate"] is not None and a["ic_winrate"] == a["ic_winrate"]]

    summary = {
        "total_alphas": len(alphas),
        "alphas": alphas,
        "aggregate": {
            "success_count": len(success),
            "failed_count": len(alphas) - len(success),
            "ic_mean_avg": round(mean(ic_means), 4) if ic_means else None,
            "icir_avg": round(mean(icirs), 4) if icirs else None,
            "winrate_avg": round(mean(winrates), 4) if winrates else None,
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[summary] saved to {SUMMARY_PATH}")

    # ── Print comparison table ──
    print("\n" + "=" * 100)
    print(f"  Multi-Alpha E2E Summary (alpha-001 ~ alpha-005)")
    print("=" * 100)
    header = (
        f"{'Alpha':<8} {'Status':<8} {'IC 均值':>10} {'ICIR':>10} {'胜率':>8} "
        f"{'Code':>6} {'耗时':>8} {'备注':<20}"
    )
    print(header)
    print("-" * 100)
    for a in alphas:
        ic = a["ic_mean"]
        ic_str = f"{ic:+.4f}" if isinstance(ic, (int, float)) and ic == ic else "  NaN"
        icir = a["icir"]
        icir_str = f"{icir:+.4f}" if isinstance(icir, (int, float)) and icir == icir else "  NaN"
        wr = a["ic_winrate"]
        wr_str = f"{wr * 100:5.1f}%" if isinstance(wr, (int, float)) and wr == wr else "  NaN"
        code_n = a["code_chars"] or 0
        elapsed = a["elapsed_sec"] or 0
        note = a["stage"] if a["status"] != "success" else ""
        print(
            f"{a['name']:<8} {a['status']:<8} {ic_str:>10} {icir_str:>10} {wr_str:>8} "
            f"{code_n:>6} {elapsed:>7.1f}s {note:<20}"
        )
    print("-" * 100)

    agg = summary["aggregate"]
    print(
        f"  SUCCESS: {agg['success_count']}/{len(alphas)}  "
        f"avg IC: {agg['ic_mean_avg']}  "
        f"avg ICIR: {agg['icir_avg']}  "
        f"avg 胜率: {(agg['winrate_avg'] or 0) * 100:.1f}%"
    )
    if agg["failed_count"] > 0:
        print(f"\n  FAILED alphas (likely pd.qcut tie issue in GroupAnalyzer):")
        for a in alphas:
            if a["status"] != "success":
                print(f"    {a['name']}: {a['stage']} - {a.get('ic_mean', 'no IC')}")


if __name__ == "__main__":
    main()
