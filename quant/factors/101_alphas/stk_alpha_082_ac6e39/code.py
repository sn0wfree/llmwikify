def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # Part 1: rank(decay_linear(delta(open, 1.46063), 14.8717))
    delta_open = delta(pl.col('open'), periods=1)
    decay_1 = decay_linear(delta_open, window=15)
    rank_1 = rank(decay_1).over('date')

    # Part 2: Ts_Rank(decay_linear(correlation(IndNeutralize(volume, sector), open, 17.4842), 6.92131), 13.4283)
    # (open * 0.634196) + (open * (1 - 0.634196)) simplifies to open
    # Using neutralize as substitute for IndNeutralize (no sector classification available)
    neutralized_volume = neutralize(pl.col('volume')).over('date')
    corr = rolling_corr(neutralized_volume, pl.col('open'), window=17)
    decay_2 = decay_linear(corr, window=7)
    ts_rank_2 = ts_rank(decay_2, window=13)

    # min of the two parts, then negate
    factor = -1 * pl.min_horizontal([rank_1, ts_rank_2])

    return df.select(factor).to_series()