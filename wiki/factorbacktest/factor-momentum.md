---
title: Factor Backtest — momentum
type: FactorBacktest
factor_ref: momentum
universe: HS300
adj_mode: M-end
hedge: equal
start: 2023-01-01
end: 2024-12-31
ic_mean: 0.0077
rank_ic_mean: -0.0698
icir: 0.0316
rank_icir: -0.3575
win_rate: 0.3333
annual_return: 0.0786
longshort_ann_return: 0.2722
longshort_sharpe: 1.1232
data_source: cache+clickhouse
status: success
---

# Factor Backtest — momentum

- Universe: `HS300`
- Adj mode: `M-end`
- Hedge: `equal`
- Window: 2023-01-01 → 2024-12-31
- Data source: cache+clickhouse

## IC Analysis

| Metric | Value |
|---|---|
| IC Mean | 0.0077 |
| IC Std | 0.2420 |
| ICIR | 0.0316 |
| t-stat | 0.1095 |
| Win Rate | 0.3333 |
| Rank IC Mean | -0.0698 |
| Rank ICIR | -0.3575 |

## Quantile Returns

| Group | Annual Return |
|---|---|
| G1 | 0.0675 |
| G2 | 0.0641 |
| G3 | 0.0384 |
| G4 | 0.0443 |
| G5 | 0.0786 |

## Long-Short

| Metric | Value |
|---|---|
| Ann Return | 0.2722 |
| Sharpe | 1.1232 |
| Max DD | 0.0463 |
