def compute_factor(df: pl.DataFrame) -> pl.Series:
    # ts_rank(volume, 5)
    rank_volume = ts_rank(pl.col('volume'), window=5)

    # ts_rank(high, 5)
    rank_high = ts_rank(pl.col('high'), window=5)

    # correlation(ts_rank(volume, 5), ts_rank(high, 5), 5)
    corr = correlation(rank_volume, rank_high, window=5)

    # ts_max(correlation, 3) — use rolling_max as ts_max equivalent
    max_corr = rolling_max(corr, window=3)

    # -1 * ts_max(...)
    factor = -1 * max_corr

    return df.select(factor).to_series()