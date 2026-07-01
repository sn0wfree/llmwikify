"""Compare old (react_engine) vs new (unified codegen) results.

Usage:
    python3 scripts/compare_old_vs_new.py

Compares:
    - _baseline_20260624/ (old react_engine results)
    - scripts/output/ (new unified codegen results)
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT = Path(__file__).parent / "output"
BASELINE = OUTPUT / "_baseline_20260624"


def load_alpha(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main() -> None:
    print("=" * 90)
    print("  Old (react_engine) vs New (unified codegen) Comparison")
    print("=" * 90)

    old_success = []
    new_success = []
    old_failed = []
    new_failed = []
    both_ok = []
    new_only_fail = []

    for idx in range(1, 102):
        old = load_alpha(BASELINE / f"single_factor_{idx:03d}.json")
        new = load_alpha(OUTPUT / f"single_factor_{idx:03d}.json")

        old_ok = old and old.get("status") == "success"
        new_ok = new and new.get("status") == "success"

        if old_ok:
            old_success.append(idx)
        else:
            old_failed.append(idx)
        if new_ok:
            new_success.append(idx)
        else:
            new_failed.append(idx)

        if old_ok and new_ok:
            both_ok.append(idx)
        elif old_ok and not new_ok:
            new_only_fail.append(idx)

    print(f"\n{'':>8} {'Old':>10} {'New':>10} {'Delta':>10}")
    print(f"  {'Success':>6} {len(old_success):>10} {len(new_success):>10} {len(new_success)-len(old_success):>+10}")
    print(f"  {'Failed':>6} {len(old_failed):>10} {len(new_failed):>10} {len(new_failed)-len(old_failed):>+10}")

    # ── IC / ICIR / Winrate 对比（只对比两者都成功的 alpha）──
    if both_ok:
        old_ics, new_ics = [], []
        old_icirs, new_icirs = [], []
        old_wrs, new_wrs = [], []
        old_elapsed, new_elapsed = [], []

        for idx in both_ok:
            old = load_alpha(BASELINE / f"single_factor_{idx:03d}.json")
            new = load_alpha(OUTPUT / f"single_factor_{idx:03d}.json")
            if old.get("ic_mean") is not None and new.get("ic_mean") is not None:
                old_ics.append(old["ic_mean"])
                new_ics.append(new["ic_mean"])
            if old.get("icir") is not None and new.get("icir") is not None:
                old_icirs.append(old["icir"])
                new_icirs.append(new["icir"])
            if old.get("ic_winrate") is not None and new.get("ic_winrate") is not None:
                old_wrs.append(old["ic_winrate"])
                new_wrs.append(new["ic_winrate"])
            old_elapsed.append(old.get("elapsed_sec", 0))
            new_elapsed.append(new.get("elapsed_sec", 0))

        def avg(lst):
            return sum(lst) / len(lst) if lst else 0

        print(f"\n{'':>8} {'Old':>12} {'New':>12} {'Delta':>12}")
        print(f"  {'Avg IC':>6} {avg(old_ics):>+12.4f} {avg(new_ics):>+12.4f} {avg(new_ics)-avg(old_ics):>+12.4f}")
        print(f"  {'Avg ICIR':>6} {avg(old_icirs):>+12.4f} {avg(new_icirs):>+12.4f} {avg(new_icirs)-avg(old_icirs):>+12.4f}")
        print(f"  {'Avg WR':>6} {avg(old_wrs)*100:>11.1f}% {avg(new_wrs)*100:>11.1f}% {(avg(new_wrs)-avg(old_wrs))*100:>+11.1f}%")
        print(f"  {'Avg Time':>6} {avg(old_elapsed):>11.1f}s {avg(new_elapsed):>11.1f}s {avg(new_elapsed)-avg(old_elapsed):>+11.1f}s")
        print(f"\n  共同成功: {len(both_ok)} 个 alpha")

    # ── 新路径失败的 alpha ──
    if new_only_fail:
        print(f"\n  ⚠ 新路径失败但旧路径成功的 alpha:")
        for idx in new_only_fail:
            new = load_alpha(OUTPUT / f"single_factor_{idx:03d}.json")
            stage = new.get("stage", "?") if new else "missing"
            err = (new.get("error", "?") or "?")[:80] if new else "file missing"
            print(f"    alpha-{idx:03d}: {stage} - {err}")

    # ── 逐 alpha 符号对比 ──
    if both_ok:
        sign_diff = []
        for idx in both_ok:
            old = load_alpha(BASELINE / f"single_factor_{idx:03d}.json")
            new = load_alpha(OUTPUT / f"single_factor_{idx:03d}.json")
            old_ic = old.get("ic_mean", 0) or 0
            new_ic = new.get("ic_mean", 0) or 0
            if old_ic != 0 and new_ic != 0:
                if (old_ic > 0) != (new_ic > 0):
                    sign_diff.append(idx)
        if sign_diff:
            print(f"\n  ℹ IC 符号翻转: {len(sign_diff)} 个（LLM 随机性，正常）")

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()
