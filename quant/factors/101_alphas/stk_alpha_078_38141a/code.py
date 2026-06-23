def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv40: average daily volume over 40 days
    adv40 = rolling_mean(pl.col('volume'), window=40)

    # First component: rank(correlation(sum(low*0.352233 + vwap*(1-0.352233), 20), sum(adv40, 20), 7))
    inner1 = pl.col('low') * 0.352233 + pl.col('vwap') * (1 - 0.352233)
    sum_inner1 = rolling_sum(inner1, window=20)
    sum_adv40 = rolling_sum(adv40, window=20)
    corr1 = rolling_corr(sum_inner1, sum_adv40, window=7)
    rank1 = rank(corr1).over('date')

    # Second component: rank(correlation(rank(vwap), rank(volume), 6))
    rank_vwap = rank(pl.col('vwap')).over('date')
    rank_vol = rank(pl.col('volume')).over('date')
    corr2 = rolling_corr(rank_vwap, rank_vol, window=6)
    rank2 = rank(corr2).over('date')

    # Final: rank1 ^ rank2 (exponentiation)
    factor = rank1 ** rank2

    return df.select(factor).to_series()