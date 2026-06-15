#!/usr/bin/env python3
"""分步交叉验证 — 严格对齐 server 算法.

Step 1-6, 每步独立于 factor_backtest.py.
"""

import sys, numpy as np, pandas as pd

sys.path.insert(0, "src")
from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe
from llmwikify.reproduction.metrics import evaluation

# ── 数据 ──────────────────────────────────────────────────
df_raw = pd.read_parquet("/tmp/hs300_full.parquet")
close = (
    df_raw.pivot_table(index="date", columns="Code", values="close", aggfunc="last")
    .sort_index().dropna(how="all")
)

# ── Server ground truth ──────────────────────────────────
sv = run_factor_backtest_universe(
    close_wide=close, factor_class="momentum", factor_params={"period": 20},
    adj_mode="M-end", n_groups=5, universe="hs300",
)

# ── Step 1: Factor matrix (per-stock dropna pct_change) ──
factor_wide = close.copy()
factor_wide[:] = np.nan
for code in close.columns:
    s = close[code].dropna()
    if len(s) < 5:
        continue
    mom = s.pct_change(20)
    mom.index = s.index[:len(mom)]
    factor_wide[code] = mom

# Step 2: Forward return (用默认 fill_method='pad' 匹配 server)
ret1d = close.pct_change(1).shift(-1)

adj_dates = [pd.Timestamp(ic["date"]) for ic in sv.ic_series]

print("=" * 72)
header = f"{'STEP':<6} {'CHECK':<20} {'SERVER':>12} {'MY':>12} {'DIFF':>12} {'RESULT':>6}"
print(header)
print("-" * 72)

pass_cnt = 0; fail_cnt = 0

def check(name, sv_val, my_val, eps=1e-4):
    global pass_cnt, fail_cnt
    sv_f = float(sv_val); my_f = float(my_val)
    d = abs(sv_f - my_f)
    ok = d < eps
    if ok: pass_cnt += 1
    else: fail_cnt += 1
    print(f"{'':6} {name:<20} {sv_f:>12.6f} {my_f:>12.6f} {d:>12.6f} {'PASS' if ok else f'FAIL(d={d:.4f})':>6}")

# ── Step 3: IC per adj_date ──────────────────────────────
for i, d in enumerate(adj_dates):
    fv = factor_wide.loc[d].dropna()
    rv = ret1d.loc[d].dropna()
    common = fv.index.intersection(rv.index)
    ic = np.corrcoef(fv[common].values, rv[common].values)[0,1]
    ric = pd.Series(fv[common].rank()).corr(pd.Series(rv[common].rank()))

    si = sv.ic_series[i]
    check(f"IC[{i}]", si["ic"], ic)
    check(f"RankIC[{i}]", si["rank_ic"], ric)
    check(f"n_stk[{i}]", si["n_stocks"], len(common))

# ── Step 4: Quantile group period returns ────────────────
# ⚠️ 必须用 range(len-1) 匹配 server: 最后一个是终点, 不需要 next-period return
period_ret = []
for i in range(len(adj_dates) - 1):
    d = adj_dates[i]
    fv = factor_wide.loc[d].dropna()
    rv = ret1d.loc[d].dropna()
    common = fv.index.intersection(rv.index)
    f_al = fv.loc[common].rank(method="first")
    groups = pd.qcut(f_al, 5, labels=range(1, 6), duplicates="drop").astype(int)
    d_ret = {}
    for g in range(1, 6):
        m = groups[groups == g].index
        d_ret[f"G{g}"] = float(rv.loc[m].mean()) if len(m) else 0.0
        d_ret[f"G{g}_n"] = len(m)
    period_ret.append(d_ret)

# ── Step 5: Quantile NAV curves ──────────────────────────
qcurves = {f"G{g}": [] for g in range(1, 6)}
for g in range(1, 6):
    gl = f"G{g}"
    nav = 1.0
    for entry in period_ret:
        qcurves[gl].append(nav)
        nav *= 1 + entry[gl]

# LS NAV = G5 - G1 + 1 (pointwise, as in server's _compute_long_short)
ls_nav = [g5 - g1 + 1 for g5, g1 in zip(qcurves["G5"], qcurves["G1"])]

# Compare LS NAV
for i in range(len(ls_nav)):
    sv_ls = sv.longshort_curve
    if i < len(sv_ls):
        check(f"LS_NAV[{i}]", sv_ls[i]["value"], ls_nav[i])

# ── Step 6: evaluation() metrics ─────────────────────────
ls_s = pd.Series(ls_nav, index=[str(d)[:10] for d in adj_dates[:len(ls_nav)]])
ev = evaluation(ls_s, list(ls_s.index))

check("LS_Ann", sv.longshort_ann_return, ev["annual_return"])
check("LS_Sharpe", sv.longshort_sharpe, ev["sharpe"])
check("LS_MDD", sv.longshort_mdd, ev["max_drawdown"])

# IC time-series mean (per adj_date, common stocks only)
my_ic_list = []
for d in adj_dates:
    fv = factor_wide.loc[d].dropna()
    rv = ret1d.loc[d].dropna()
    common = fv.index.intersection(rv.index)
    my_ic_list.append(np.corrcoef(fv[common].values, rv[common].values)[0,1])
my_ic_mean = np.mean(my_ic_list)
check("IC_Mean", sv.ic_mean, my_ic_mean)

print("-" * 72)
print(f"{'':6} {'':20} {'':>12} {'':>12} {'':>12} {f'PASS={pass_cnt} FAIL={fail_cnt}':>6}")
print("=" * 72)
print(f"OVERALL: {'✅ PASS' if fail_cnt == 0 else '❌ FAIL'}")
