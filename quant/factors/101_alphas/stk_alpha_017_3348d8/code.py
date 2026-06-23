def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Component 1: -1 * rank(ts_rank(close, 10))
    ts_rank_close_10 = ts_rank(pl.col('close'), window=10)
    part1 = -1 * rank(ts_rank_close_10).over('date')

    # Component 2: rank(delta(delta(close, 1), 1))
    delta_close_1 = delta(pl.col('close'), periods=1)
    delta_delta_close = delta(delta_close_1, periods=1)
    part2 = rank(delta_delta_close).over('date')

    # Component 3: rank(ts_rank((volume / adv20), 5))
    adv20 = rolling_mean(pl.col('volume'), window=20)
    vol_ratio = pl.col('volume') / adv20
    ts_rank_vol_5 = ts_rank(vol_ratio, window=5)
    part3 = rank(ts_rank_vol_5).over('date')

    # Combine all three components
    factor = part1 * part2 * part3

    return df.select(factor).to_series()