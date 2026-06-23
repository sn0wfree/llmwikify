def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv40 = rolling mean of volume over 40 days
    df = df.with_columns(
        rolling_mean(pl.col('volume'), window=40).alias('_adv40')
    )

    # Part 1: rank((open - ts_min(open, 12.4105)))  -> window=12
    ts_min_open = ts_min(pl.col('open'), window=12)
    part1_inner = pl.col('open') - ts_min_open
    # Materialize before cross-section rank
    df = df.with_columns(part1_inner.alias('_part1_inner'))
    part1 = rank(pl.col('_part1_inner')).over('date')

    # Part 2 inner: correlation(sum((high+low)/2, 19.1351), sum(adv40, 19.1351), 12.8742)
    sum_hl = rolling_sum((pl.col('high') + pl.col('low')) / 2, window=19)
    sum_adv = rolling_sum(pl.col('_adv40'), window=19)
    corr_expr = correlation(sum_hl, sum_adv, window=13)

    # Materialize the time-series correlation BEFORE cross-section rank
    df = df.with_columns(corr_expr.alias('_corr'))
    rank_corr = rank(pl.col('_corr')).over('date')
    powered = rank_corr ** 5

    # Materialize powered, then apply ts_rank with window=12
    df = df.with_columns(powered.alias('_powered'))
    part2 = ts_rank(pl.col('_powered'), window=12)

    # Final: part1 < part2 -> cast boolean to float
    factor = (part1 < part2).cast(pl.Float32)

    return df.select(factor).to_series()