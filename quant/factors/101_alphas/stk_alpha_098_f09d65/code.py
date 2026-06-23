def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Part 1: rank(decay_linear(correlation(vwap, sum(adv5, 26.4719), 4.58418), 7.18088))
    adv5 = rolling_mean(pl.col('volume'), window=5)
    sum_adv5 = rolling_sum(adv5, window=26)
    corr1 = rolling_corr(pl.col('vwap'), sum_adv5, window=4)
    decay1 = decay_linear(corr1, window=7)
    rank1 = rank(decay1).over('date')

    # Part 2: rank(decay_linear(Ts_Rank(Ts_ArgMin(correlation(rank(open), rank(adv15), 20.8187), 8.62571), 6.95668), 8.07206))
    adv15 = rolling_mean(pl.col('volume'), window=15)
    rank_open = rank(pl.col('open')).over('date')
    rank_adv15 = rank(adv15).over('date')
    corr2 = rolling_corr(rank_open, rank_adv15, window=20)
    argmin_corr2 = ts_argmin(corr2, window=8)
    ts_rank2 = ts_rank(argmin_corr2, window=6)
    decay2 = decay_linear(ts_rank2, window=8)
    rank2 = rank(decay2).over('date')

    factor = rank1 - rank2
    return df.select(factor).to_series()