def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv30: 30-day rolling mean of volume
    adv30 = rolling_mean(pl.col('volume'), window=30)

    # sum(adv30, 37.4843) -> rolling sum window 37
    sum_adv30 = rolling_sum(adv30, window=37)

    # correlation(close, sum(adv30, 37.4843), 15.1365) -> rolling corr window 15
    corr1 = rolling_corr(pl.col('close'), sum_adv30, window=15)

    # weighted price: 0.0261661 * high + (1 - 0.0261661) * vwap
    weighted = (pl.col('high') * 0.0261661) + (pl.col('vwap') * (1 - 0.0261661))

    # cross-sectional ranks
    rank_weighted = rank(weighted).over('date')
    rank_vol = rank(pl.col('volume')).over('date')

    # correlation(rank(weighted), rank(volume), 11.4791) -> rolling corr window 11
    corr2 = rolling_corr(rank_weighted, rank_vol, window=11)

    # cross-sectional ranks of the two correlations
    rank_corr1 = rank(corr1).over('date')
    rank_corr2 = rank(corr2).over('date')

    # (rank_corr1 < rank_corr2) * -1
    factor = pl.when(rank_corr1 < rank_corr2).then(-1).otherwise(0)

    return df.select(factor).to_series()