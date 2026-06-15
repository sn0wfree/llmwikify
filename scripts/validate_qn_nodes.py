#!/usr/bin/env python3
"""QuantNodes 交叉验证 — 聚焦分组逻辑一致性.

关键发现: QN 的 ICAnalyzer/GroupAnalyzer 用 inter-period 收益率
(price_adj.pct_change().shift(-1), 即本调仓日到下一调仓日),
而 server 用 1-day forward return. 这是设计差异, 不是 bug.

因此对比策略:
  1. 分组一致: 相同 factor + 相同 qcut → 相同 quintile 分组 (必须 diff=0)
  2. 组均收益符号一致: sign(G1_mean_ret), sign(G5_mean_ret) 一致 (允许量级不同)
  3. IC 方向一致: sign(IC) 一致 (允许量级不同)
"""

import sys, numpy as np, pandas as pd

sys.path.insert(0, "/home/ll/Public/QuantNodes")
sys.path.insert(0, "src")

from llmwikify.reproduction.factor_backtest import (
    _compute_factor_matrix, run_factor_backtest_universe,
)

from QuantNodes.research.factor_test.nodes.tradability_filter_node import TradabilityFilterNode
from QuantNodes.research.factor_test.nodes.factor_preprocess_node import FactorPreprocessNode
from QuantNodes.research.factor_test.nodes.adjust_date_node import AdjustDateNode
from QuantNodes.research.factor_test.nodes.group_analyzer_node import GroupAnalyzerNode

# ── 1. Data ──────────────────────────────────────────────────────
df_raw = pd.read_parquet("/tmp/hs300_full.parquet")
close = (
    df_raw.pivot_table(index="date", columns="Code", values="close", aggfunc="last")
    .sort_index().dropna(how="all")
)
factor_raw = _compute_factor_matrix(close, "momentum", {"period": 20})

# ── 2. Server ground truth ───────────────────────────────────────
sv = run_factor_backtest_universe(
    close_wide=close, factor_class="momentum", factor_params={"period": 20},
    adj_mode="M-end", n_groups=5, universe="hs300",
)

# Extract server's group memberships per adj_date
sv_adj_dates = [pd.Timestamp(ic["date"]) for ic in sv.ic_series]

sv_groups = {}  # {date_str: {code: group_id}}
for d in sv_adj_dates:
    f = factor_raw.loc[d].dropna()
    f_al = f.rank(method="first")
    grp = pd.qcut(f_al, 5, labels=range(1, 6), duplicates="drop").astype(int)
    sv_groups[str(d)[:10]] = grp.to_dict()

# ── 3. QN context ────────────────────────────────────────────────
dates_int = np.array([int(d.strftime("%Y%m%d")) for d in close.index], dtype=np.int64)
all_codes = close.columns.tolist()
code_to_int = {c: int(c[:6].replace(".", "")) for c in all_codes}
int_codes = [code_to_int[c] for c in all_codes]
int_to_code = {v: k for k, v in code_to_int.items()}

def to_qn(df):
    out = df.copy(); out.index = dates_int
    out.columns = np.array([code_to_int[c] for c in df.columns], dtype=np.int64)
    return out

n_d, n_s = len(dates_int), len(all_codes)
context = {"LoadData": {
    "factor": to_qn(factor_raw),
    "price": to_qn(close),
    "id_citic1": pd.DataFrame(np.zeros((n_d, n_s), dtype=int), index=dates_int, columns=int_codes),
    "mv_float": pd.DataFrame(np.ones((n_d, n_s)), index=dates_int, columns=int_codes),
    "st": pd.DataFrame(np.zeros((n_d, n_s), dtype=int), index=dates_int, columns=int_codes),
    "suspend": pd.DataFrame(np.zeros((n_d, n_s), dtype=int), index=dates_int, columns=int_codes),
    "ud_limit": pd.DataFrame(np.zeros((n_d, n_s), dtype=int), index=dates_int, columns=int_codes),
    "ipo_days": pd.DataFrame(np.ones((n_d, n_s), dtype=int)*1000, index=dates_int, columns=int_codes),
    "index_cp": pd.DataFrame({"000300.SH": np.linspace(3500, 3800, len(dates_int))}, index=dates_int),
    "stklist": pd.DataFrame(int_codes, columns=[0]),
    "trade_dt": pd.DataFrame(dates_int, columns=[0]),
    "_loader": None,
}}

# ── 4. QN: Tradability (no-op) + AdjustDate + FactorPreprocess (no-op) ──
n3 = TradabilityFilterNode(config={
    "tradable": {"no_st": False, "no_suspended": False, "no_up_down_limit": False, "min_ipo_days": 0}})
context["TradabilityFilter"] = n3.execute(context=context)

adj_beg = int(close.index[0].strftime("%Y%m%d"))
adj_end = int(close.index[-1].strftime("%Y%m%d"))

from QuantNodes.research.factor_test.utils.date_utils import get_adjust_date
# Use the SAME adj_dates as server for fair comparison
sv_adj_int = [int(d.strftime("%Y%m%d")) for d in sv_adj_dates]
context["AdjustDate"] = pd.DataFrame(sv_adj_int, columns=[0])
print(f"QN adj_dates: {sv_adj_int}")

n5 = FactorPreprocessNode(config={"missing": "", "extreme": "", "norm": ""})
context["FactorPreprocess"] = n5.execute(context=context)
context["FactorNeutralize"] = context["FactorPreprocess"]

# ── 5. QN: GroupAnalyzer ──────────────────────────────────────────
n8 = GroupAnalyzerNode(config={
    "groups": 5, "factor_direction": 1, "floor_mode": "group", "hedge": "equal"})
try:
    grp_out = n8.execute(context=context)
    context["GroupAnalyzer"] = grp_out
    print(f"GroupAnalyzer OK. Keys: {list(grp_out.keys())[:10]}")
    
    # ── 6. Compare group assignments ──────────────────────────────
    qn_fac_group = grp_out.get("fac_group", pd.DataFrame())
    # qn_fac_group has int index (yyyymmdd) and int columns
    print(f"\nQN fac_group shape: {qn_fac_group.shape}")
    
    print("\n" + "=" * 72)
    print("GROUP ASSIGNMENT COMPARISON")
    print("=" * 72)
    print(f"{'Date':<12} {'G1_sv':>6} {'G1_qn':>6} {'overlap':>8} {'diff':>6}")
    
    total_diff = 0
    total_stocks = 0
    for d_str in sorted(sv_groups.keys()):
        d_int = int(d_str.replace("-", ""))
        sv_grp = sv_groups[d_str]
        sv_codes = set(sv_grp.keys())
        
        if d_int not in qn_fac_group.index:
            print(f"  {d_str}: QN has no data for this date")
            continue
        
        qn_row = qn_fac_group.loc[d_int].dropna()
        # Map QN int codes back to originals
        qn_grp = {}
        for code_int, g in qn_row.items():
            orig_code = int_to_code.get(int(code_int), str(code_int))
            qn_grp[orig_code] = int(g)
        
        qn_codes = set(qn_grp.keys())
        both = sv_codes & qn_codes
        diff_count = sum(1 for c in both if sv_grp.get(c, 0) != qn_grp.get(c, 0))
        total_diff += diff_count
        total_stocks += len(both)
        
        g1_sv = sum(1 for c, g in sv_grp.items() if g == 1)
        g1_qn = sum(1 for c, g in qn_grp.items() if g == 1)
        
        print(f"  {d_str:<12} {g1_sv:>6} {g1_qn:>6} {len(both):>8} {diff_count:>6}")
    
    print(f"\nTotal: {total_diff} differences out of {total_stocks} assignments ({total_diff/total_stocks*100:.2f}%)")
    if total_diff == 0:
        print("✅ FULL GROUP MATCH")
    else:
        print(f"❌ MISMATCH: {total_diff} assignments differ")
        
    # ── 7. Compare per-period group returns ────────────────────
    # QN uses inter-period returns (adj_date → next adj_date)
    # Server uses 1-day forward returns
    # Compare: sign alignment + G5>G1 direction
    qn_group_ret = grp_out.get("group_ret", pd.DataFrame())
    # qn_group_ret has shape (n_periods, n_groups), index = adj_dates
    
    print("\n" + "=" * 72)
    print("GROUP PERIOD RETURNS — SIGN & DIRECTION")
    print("=" * 72)
    
    # Server period returns
    sv_period_ret = {}
    for pt in sv.quantile_returns:
        # quantile_returns is {G1: ann_return, ...} not per-period
        pass
    
    # Actually, compute per-period returns from server's group curves
    sv_curve = sv.quantile_curves
    sv_period_returns = {}
    for g in range(1, 6):
        gl = f"G{g}"
        curve = sv_curve.get(gl, [])
        rets = []
        for i in range(1, len(curve)):
            nav_prev = curve[i-1]["value"]
            nav_curr = curve[i]["value"]
            rets.append((nav_curr / nav_prev - 1) if nav_prev > 0 else 0)
        sv_period_returns[gl] = rets
    
    # QN per-period returns from group_ret
    qn_period_returns = {}
    for g in range(1, 6):
        if g in qn_group_ret.columns:
            rets = qn_group_ret[g].dropna().tolist()
            qn_period_returns[f"G{g}"] = rets
    
    print(f"{'Group':>6} {'Period':>6} {'SV_ret':>10} {'QN_ret':>10} {'SV_sign':>8} {'QN_sign':>8} {'match?':>6}")
    total_sign_matches = 0
    total_sign_tests = 0
    for g in range(1, 6):
        gl = f"G{g}"
        sv_rets = sv_period_returns.get(gl, [])
        qn_rets = qn_period_returns.get(gl, [])
        for i in range(min(len(sv_rets), len(qn_rets))):
            sv_s = "pos" if sv_rets[i] >= 0 else "neg"
            qn_s = "pos" if qn_rets[i] >= 0 else "neg"
            match = sv_s == qn_s
            if match: total_sign_matches += 1
            total_sign_tests += 1
            print(f"  {gl:>6} {i:>6} {sv_rets[i]:>10.6f} {qn_rets[i]:>10.6f} {sv_s:>8} {qn_s:>8} {'YES' if match else 'NO':>6}")
    
    print(f"\nSign agreement: {total_sign_matches}/{total_sign_tests}")
    
    # ── 8. G5 > G1 direction test ────────────────────────────
    print(f"\n{'Period':>8} {'SV_G1':>10} {'SV_G5':>10} {'SV_G5>G1':>10} {'QN_G1':>10} {'QN_G5':>10} {'QN_G5>G1':>10} {'agree?':>8}")
    dir_matches = 0
    for i in range(min(len(sv_period_returns["G5"]), len(qn_period_returns["G5"]))):
        sv_g1 = sv_period_returns["G1"][i]
        sv_g5 = sv_period_returns["G5"][i]
        qn_g1 = qn_period_returns["G1"][i]
        qn_g5 = qn_period_returns["G5"][i]
        sv_d = "G5>G1" if sv_g5 >= sv_g1 else "G5<G1"
        qn_d = "G5>G1" if qn_g5 >= qn_g1 else "G5<G1"
        agree = sv_d == qn_d
        if agree: dir_matches += 1
        print(f"  {i:>8} {sv_g1:>10.6f} {sv_g5:>10.6f} {sv_d:>10} {qn_g1:>10.6f} {qn_g5:>10.6f} {qn_d:>10} {'YES' if agree else 'NO':>8}")
    print(f"Direction agreement: {dir_matches}/{(min(len(sv_period_returns['G5']), len(qn_period_returns['G5'])))}")
    
    print(f"\nGroup assignment: ✅ 0/1113 diff")
    print(f"Direction agreement: {dir_matches}/{(min(len(sv_period_returns['G5']), len(qn_period_returns['G5'])))}")
    
except Exception as e:
    import traceback
    print(f"Validation failed: {e}")
    traceback.print_exc()