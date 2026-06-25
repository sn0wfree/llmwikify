#!/usr/bin/env python3
"""Analyze 101 alpha results and generate summary report."""

import json
import statistics
from pathlib import Path


def load_results(output_dir: Path) -> list[dict]:
    results = []
    for f in sorted(output_dir.glob("single_factor_*.json")):
        if "_noreact" in f.stem:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            results.append(d)
        except Exception:
            continue
    return results


def compute_stats(values: list[float]) -> dict:
    valid = [v for v in values if v is not None]
    if not valid:
        return {"count": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    return {
        "count": len(valid),
        "mean": statistics.mean(valid),
        "median": statistics.median(valid),
        "std": statistics.stdev(valid) if len(valid) > 1 else 0.0,
        "min": min(valid),
        "max": max(valid),
    }


def generate_report(results: list[dict]) -> str:
    lines = [
        "# 101-Alpha 分析报告",
        "",
        f"- 总数: {len(results)}",
        f"- 成功: {sum(1 for r in results if r.get('status') == 'success')}",
        f"- 失败: {sum(1 for r in results if r.get('status') != 'success')}",
        "",
    ]

    # IC analysis
    ic_values = [r.get("ic_mean") for r in results if r.get("ic_mean") is not None]
    ic_stats = compute_stats(ic_values)
    lines.append("## IC 分析")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 有效数量 | {ic_stats['count']}/{len(results)} |")
    if ic_stats["mean"] is not None:
        lines.append(f"| 均值 | {ic_stats['mean']:+.4f} |")
        lines.append(f"| 中位数 | {ic_stats['median']:+.4f} |")
        lines.append(f"| 标准差 | {ic_stats['std']:.4f} |")
        lines.append(f"| 最小值 | {ic_stats['min']:+.4f} |")
        lines.append(f"| 最大值 | {ic_stats['max']:+.4f} |")
        lines.append(f"| |IC|>0.01 | {sum(1 for v in ic_values if abs(v) > 0.01)}/{len(ic_values)} |")
        lines.append(f"| |IC|>0.02 | {sum(1 for v in ic_values if abs(v) > 0.02)}/{len(ic_values)} |")
    lines.append("")

    # ICIR analysis
    icir_values = [r.get("icir") for r in results if r.get("icir") is not None]
    icir_stats = compute_stats(icir_values)
    lines.append("## ICIR 分析")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 有效数量 | {icir_stats['count']}/{len(results)} |")
    if icir_stats["mean"] is not None:
        lines.append(f"| 均值 | {icir_stats['mean']:+.4f} |")
        lines.append(f"| 中位数 | {icir_stats['median']:+.4f} |")
        lines.append(f"| |ICIR|>0.1 | {sum(1 for v in icir_values if abs(v) > 0.1)}/{len(icir_values)} |")
        lines.append(f"| |ICIR|>0.2 | {sum(1 for v in icir_values if abs(v) > 0.2)}/{len(icir_values)} |")
    lines.append("")

    # Win rate analysis
    wr_values = [r.get("ic_winrate") for r in results if r.get("ic_winrate") is not None]
    wr_stats = compute_stats(wr_values)
    lines.append("## 胜率分析")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 有效数量 | {wr_stats['count']}/{len(results)} |")
    if wr_stats["mean"] is not None:
        lines.append(f"| 均值 | {wr_stats['mean']*100:.1f}% |")
        lines.append(f"| 中位数 | {wr_stats['median']*100:.1f}% |")
        lines.append(f"| >50% | {sum(1 for v in wr_values if v > 0.5)}/{len(wr_values)} |")
        lines.append(f"| >55% | {sum(1 for v in wr_values if v > 0.55)}/{len(wr_values)} |")
    lines.append("")

    # Top/bottom by IC
    sorted_by_ic = sorted(results, key=lambda r: abs(r.get("ic_mean") or 0), reverse=True)
    lines.append("## Top 10 (|IC|)")
    lines.append("")
    lines.append("| # | Alpha | IC | ICIR | 胜率 |")
    lines.append("|---|---|---|---|---|")
    for r in sorted_by_ic[:10]:
        idx = r.get("alpha_index", "?")
        ic = r.get("ic_mean")
        icir = r.get("icir")
        wr = r.get("ic_winrate")
        lines.append(
            f"| {idx} | alpha-{idx:03d} | {ic:+.4f} | {icir:+.4f} | {wr*100:.1f}% |"
            if ic is not None and icir is not None and wr is not None
            else f"| {idx} | alpha-{idx:03d} | - | - | - |"
        )
    lines.append("")

    lines.append("## Bottom 10 (|IC|)")
    lines.append("")
    lines.append("| # | Alpha | IC | ICIR | 胜率 |")
    lines.append("|---|---|---|---|---|")
    for r in sorted_by_ic[-10:]:
        idx = r.get("alpha_index", "?")
        ic = r.get("ic_mean")
        icir = r.get("icir")
        wr = r.get("ic_winrate")
        lines.append(
            f"| {idx} | alpha-{idx:03d} | {ic:+.4f} | {icir:+.4f} | {wr*100:.1f}% |"
            if ic is not None and icir is not None and wr is not None
            else f"| {idx} | alpha-{idx:03d} | - | - | - |"
        )
    lines.append("")

    # Execution time
    time_values = [r.get("elapsed_sec", 0) for r in results]
    time_stats = compute_stats(time_values)
    lines.append("## 执行时间")
    lines.append("")
    if time_stats["mean"] is not None:
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 平均 | {time_stats['mean']:.1f}s |")
        lines.append(f"| 中位数 | {time_stats['median']:.1f}s |")
        lines.append(f"| 总计 | {sum(time_values):.0f}s |")
    lines.append("")

    return "\n".join(lines)


def main():
    output_dir = Path("scripts/output")
    results = load_results(output_dir)
    report = generate_report(results)
    report_path = output_dir / "101_alpha_analysis.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report written to {report_path}")
    print(f"Total: {len(results)} alphas")
    # Print summary
    ic_values = [r.get("ic_mean") for r in results if r.get("ic_mean") is not None]
    if ic_values:
        print(f"Avg IC: {statistics.mean(ic_values):+.4f}")
        print(f"Avg |IC|: {statistics.mean(abs(v) for v in ic_values):.4f}")


if __name__ == "__main__":
    main()
