def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Inner blend expression: close * 0.60733 + open * (1 - 0.60733)
    blend = pl.col('close') * 0.60733 + pl.col('open') * (1 - 0.60733)

    # IndNeutralize (no industry column available, use raw blend value)
    # ind_neutral = indneutralize(blend).over('date')

    # Delta of blend (periods=1, since 1.23438 rounds to 1)
    d = delta(blend, periods=1)

    # Cross-sectional rank of delta
    rank1 = rank(d).over('date')

    # adv150: 150-day rolling mean of volume
    adv150 = rolling_mean(pl.col('volume'), window=150)

    # Ts_Rank(vwap, 3.60973) -> window=3
    ts_rank_vwap = ts_rank(pl.col('vwap'), window=3)

    # Ts_Rank(adv150, 9.18637) -> window=9
    ts_rank_adv = ts_rank(adv150, window=9)

    # Rolling correlation (window=14, since 14.6644 rounds to 14)
    corr = rolling_corr(ts_rank_vwap, ts_rank_adv, window=14)

    # Cross-sectional rank of correlation
    rank2 = rank(corr).over('date')

    # Final comparison: rank(delta) < rank(corr) -> 1.0 / 0.0
    factor = pl.when(rank1 < rank2).then(1.0).otherwise(0.0)

    return df.select(factor).to_series()