# 101-Alpha Batch Test Report

**Date**: 2026-06-22
**Tested**: 56/101 alphas (LLM Code path via ReAct compiler)
**Success rate**: 56/56 (100.0%)

## Pipeline

1. **LLM Code Path** (`factor_compiler_react.compile_to_code_react`): ReAct loop with 3 repair rounds, self-corrects via injected error feedback
2. **H5 write** (long format 1305×50)
3. **QuantNodes PipelineRunner** (12 nodes: LoadData → SamplePoolFilter → TradabilityFilter → AdjustDate → FactorPreprocess → FactorNeutralize → ICAnalyzer → GroupAnalyzer → LongShort → FactorScore → RiskCorrelation → FactorTestReport)

## Summary

| Metric | Value |
|--------|-------|
| Total tested | 56 |
| Success | 56 (100.0%) |
| Failed | 0 (0.0%) |
| With valid IC | 49 (87.5% of success) |
| Avg IC (n=49) | +0.0046 |
| Median IC | +0.0042 |
| Positive IC rate | 33/49 (67.3%) |
| Best IC | +0.0460 (alpha-012) |
| Worst IC | -0.0478 (alpha-042) |

## Top 10 by IC

| Alpha | IC | ICIR | 胜率 | Formula |
|-------|----|----|------|---------|
| alpha-012 | +0.0460 | +0.2857 | 61.0% | `(sign(delta(volume, 1)) * (-1 * delta(close, 1)))` |
| alpha-019 | +nan | +nan | nan% | `((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) ` |
| alpha-023 | +0.0351 | +0.2580 | 59.3% | `(((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)` |
| alpha-001 | +0.0326 | +0.2238 | 59.3% | `(rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns,` |
| alpha-028 | +0.0174 | +0.0982 | 50.8% | `scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - c` |
| alpha-032 | +nan | +nan | nan% | `(scale(((sum(close, 7) / 7) - close)) + (20 * scale(correlat` |
| alpha-033 | +0.0400 | +0.2871 | 59.3% | `rank((-1 * ((1 - (open / close))^1)))` |
| alpha-008 | +0.0271 | +0.1589 | 55.9% | `(-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(op` |
| alpha-022 | +0.0184 | +0.1259 | 55.9% | `(-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(` |
| alpha-005 | +0.0106 | +0.0630 | 57.6% | `(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close` |

## Bottom 10 by IC (still success)

| Alpha | IC | ICIR | 胜率 | Formula |
|-------|----|----|------|---------|
| alpha-042 | -0.0478 | -0.2846 | 31.2% | `(rank((vwap - close)) / rank((vwap + close)))` |
| alpha-031 | -0.0286 | -0.1542 | 44.1% | `(rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10` |
| alpha-003 | -0.0264 | -0.1638 | 42.4% | `(-1 * correlation(rank(open), rank(volume), 10))` |
| alpha-043 | -0.0258 | -0.1580 | 40.7% | `(ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, ` |
| alpha-006 | -0.0195 | -0.1188 | 44.1% | `(-1 * correlation(open, volume, 10))` |
| alpha-040 | -0.0191 | -0.1238 | 40.7% | `((-1 * rank(stddev(high, 10))) * correlation(high, volume, 1` |
| alpha-014 | -0.0187 | -0.1206 | 39.0% | `((-1 * rank(delta(returns, 3))) * correlation(open, volume, ` |
| alpha-007 | -0.0121 | -0.0864 | 45.8% | `((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)` |
| alpha-035 | -0.0119 | -0.0937 | 49.2% | `((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low),` |
| alpha-011 | -0.0116 | -0.0762 | 42.4% | `((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - clos` |

## Methodology Notes

- **Data**: 5-year daily panel (1305 trading days × 50 stocks, date index int64 yyyymmdd, code index stock codes)
- **Grouping**: QuantNodes GroupAnalyzerNode refactored to 2-mode dispatch (ranked vs discrete) — `_group_ranked` uses `rank('first')` + `qcut` to break ties that previously caused `pd.qcut ValueError`
- **QuantNodes patch scope**: All QuantNodes changes upstreamed, zero regression verified on 5-alphas sample (alpha-1/12/33/41/8 IC bitwise identical before/after)
- **llmwikify patch scope**: SamplePoolFilter RangeIndex → int64 yyyymmdd (monkey-patch)
- **Self-repair**: ReAct driver retries up to 3 rounds on syntax / safety / execution errors with injected feedback

## Coverage

- **Tested**: alpha-001 to alpha-056 (56 alphas)
- **Not yet tested**: alpha-057 to alpha-101 (45 alphas)
