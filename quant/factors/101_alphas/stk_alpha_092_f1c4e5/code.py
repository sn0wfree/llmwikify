def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # Part 1: decay_linear of boolean condition, then ts_rank
    cond1 = (((pl.col('high') + pl.col('low')) / 2) + pl.col('close')) < (pl.col('low') + pl.col('open'))
    cond1_float = cond1.cast(pl.Float64)
    decay1 = decay_linear(cond1_float, window=int(14.7221))
    part1 = ts_rank(decay1, window=int(18.8683))

    # Part 2: correlation of cross-section ranks, then decay, then ts_rank
    rank_low = rank(pl.col('low')).over('date')
    adv30 = rolling_mean(pl.col('volume'), window=30)
    rank_adv30 = rank(adv30).over('date')
    corr = correlation(rank_low, rank_adv30, window=int(7.58555))
    decay2 = decay_linear(corr, window=int(6.94024))
    part2 = ts_rank(decay2, window=int(6.80584))

    # Final: element-wise min of the two parts
    factor = pl.min_horizontal([part1, part2])

    return df.select(factor).to_series()