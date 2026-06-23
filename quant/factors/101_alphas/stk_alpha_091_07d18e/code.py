def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv30: 30-day average dollar volume (close * volume)
    adv30 = rolling_mean(pl.col('close') * pl.col('volume'), window=30)

    # Part 1: Ts_Rank(decay_linear(decay_linear(correlation(IndNeutralize(close, industry), volume, 9.74928), 16.398), 3.83219), 4.8667)
    # Industry neutralize is approximated as identity (no industry column available)
    ind_neutral_close = pl.col('close')
    corr1 = rolling_corr(ind_neutral_close, pl.col('volume'), window=10)
    decay1 = decay_linear(corr1, window=16)
    decay2 = decay_linear(decay1, window=4)
    ts_rank_part = ts_rank(decay2, window=5)

    # Part 2: rank(decay_linear(correlation(vwap, adv30, 4.01303), 2.6809))
    corr2 = rolling_corr(pl.col('vwap'), adv30, window=4)
    decay3 = decay_linear(corr2, window=3)
    rank_part = rank(decay3).over('date')

    # Final: ((...) - rank(...)) * -1
    factor = (ts_rank_part - rank_part) * -1

    return df.select(factor).to_series()