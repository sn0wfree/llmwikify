def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # Part A: rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10))))
    delta_10 = delta(pl.col('close'), periods=10)
    rr_delta = rank(rank(delta_10).over('date')).over('date')
    neg_rr = -1 * rr_delta
    decayed = decay_linear(neg_rr, window=10)
    part_a = rank(rank(rank(decayed).over('date')).over('date')).over('date')

    # Part B: rank((-1 * delta(close, 3)))
    delta_3 = delta(pl.col('close'), periods=3)
    part_b = rank((-1 * delta_3)).over('date')

    # Part C: sign(scale(correlation(adv20, low, 12)))
    adv20 = ts_mean(pl.col('volume'), window=20)
    corr = correlation(adv20, pl.col('low'), window=12)
    part_c = scale(corr).over('date').sign()

    factor = (part_a + part_b) + part_c

    return df.select(factor).to_series()