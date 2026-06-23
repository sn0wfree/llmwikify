def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date); do NOT re-sort
    df = df.sort(['code', 'date'])

    # adv40: 40-day rolling mean of volume
    adv40 = rolling_mean(pl.col('volume'), window=40)

    # ----- Inner expression 1 -----
    # ((((high + low) / 2) + high) - (vwap + high)) simplifies to
    # (high + low) / 2 - vwap
    expr1 = ((pl.col('high') + pl.col('low')) / 2) - pl.col('vwap')
    decayed1 = decay_linear(expr1, window=20)         # period 20.0451 -> 20
    rank1 = rank(decayed1).over('date')

    # ----- Inner expression 2 -----
    mid = (pl.col('high') + pl.col('low')) / 2
    corr_expr = rolling_corr(mid, adv40, window=3)   # period 3.1614 -> 3
    decayed2 = decay_linear(corr_expr, window=6)     # period 5.64125 -> 6
    rank2 = rank(decayed2).over('date')

    # Element-wise min of the two cross-sectional ranks
    factor = pl.min_horizontal(rank1, rank2)

    return df.select(factor).to_series()