def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date); do NOT re-sort

    # adv60: 60-day rolling mean of volume (proxy for adv60)
    adv60 = rolling_mean(pl.col('volume'), window=60)

    # sum((high + low) / 2, 20)
    mid_price = (pl.col('high') + pl.col('low')) / 2
    sum_mid = rolling_sum(mid_price, window=20)

    # sum(adv60, 20)
    sum_adv60 = rolling_sum(adv60, window=20)

    # correlation(sum_mid, sum_adv60, 9)
    corr1 = rolling_corr(sum_mid, sum_adv60, window=9)

    # rank(corr1) cross-section
    rank1 = rank(corr1).over('date')

    # correlation(low, volume, 6)
    corr2 = rolling_corr(pl.col('low'), pl.col('volume'), window=6)

    # rank(corr2) cross-section
    rank2 = rank(corr2).over('date')

    # (rank1 < rank2) * -1  → -1 if true, else 0
    factor = pl.when(rank1 < rank2).then(pl.lit(-1)).otherwise(pl.lit(0))

    return df.select(factor).to_series()