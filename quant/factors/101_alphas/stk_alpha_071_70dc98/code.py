def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv180 = rolling mean of volume over 180 days
    adv180 = rolling_mean(pl.col('volume'), window=180)

    # Part 1: Ts_Rank(decay_linear(correlation(Ts_Rank(close, 3.43976),
    #                       Ts_Rank(adv180, 12.0647), 18.0175), 4.20501), 15.6948)
    ts_rank_close = ts_rank(pl.col('close'), window=3)
    ts_rank_adv180 = ts_rank(adv180, window=12)
    corr = rolling_corr(ts_rank_close, ts_rank_adv180, window=18)
    decay1 = decay_linear(corr, window=4)
    part1 = ts_rank(decay1, window=15)

    # Part 2: Ts_Rank(decay_linear((rank(((low + open) - (vwap + vwap)))^2),
    #                       16.4662), 4.4388)
    inner2 = (pl.col('low') + pl.col('open')) - (pl.col('vwap') + pl.col('vwap'))
    ranked = rank(inner2).over('date')
    squared = ranked ** 2
    decay2 = decay_linear(squared, window=16)
    part2 = ts_rank(decay2, window=4)

    # Max of the two parts
    factor = pl.max_horizontal([part1, part2])

    return df.select(factor).to_series()