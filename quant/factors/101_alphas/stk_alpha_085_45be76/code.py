def compute_factor(df: pl.DataFrame) -> pl.Series:
    w = 0.876703

    # Component A: rank(correlation(weighted_hc, adv30, 9))
    weighted_hc = pl.col('high') * w + pl.col('close') * (1 - w)
    adv30 = rolling_mean(pl.col('volume'), window=30)
    corr_a = rolling_corr(weighted_hc, adv30, window=9)
    rank_a = rank(corr_a).over('date')

    # Component B: rank(correlation(ts_rank(mid, 3), ts_rank(vol, 10), 7))
    mid = (pl.col('high') + pl.col('low')) / 2
    ts_rank_mid = ts_rank(mid, window=3)
    ts_rank_vol = ts_rank(pl.col('volume'), window=10)
    corr_b = rolling_corr(ts_rank_mid, ts_rank_vol, window=7)
    rank_b = rank(corr_b).over('date')

    # Final: A^B
    factor = rank_a ** rank_b

    return df.select(factor).to_series()