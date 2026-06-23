def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20 = 20-day average volume (per-code time-series, no .over needed)
    adv20 = ts_mean(pl.col('volume'), 20)

    # term1: ts_rank((volume / adv20), 20)
    vol_ratio = pl.col('volume') / adv20
    part1 = ts_rank(vol_ratio, 20)

    # term2: ts_rank((-1 * delta(close, 7)), 8)
    delta_close = delta(pl.col('close'), periods=7)
    neg_delta = -1 * delta_close
    part2 = ts_rank(neg_delta, 8)

    # factor = product of the two terms
    factor = part1 * part2

    return df.select(factor).to_series()