def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Part 1 (time-series): (sum(close, 7) / 7) - close
    part1_ts = rolling_mean(pl.col('close'), window=7) - pl.col('close')

    # Materialize before cross-section scale
    df = df.with_columns(part1_ts.alias('_part1'))
    part1 = scale(pl.col('_part1')).over('date')

    # Part 2 (time-series): correlation(vwap, delay(close, 5), 230)
    part2_ts = correlation(pl.col('vwap'), delay(pl.col('close'), periods=5), window=230)

    # Materialize before cross-section scale
    df = df.with_columns(part2_ts.alias('_part2'))
    part2 = scale(pl.col('_part2')).over('date')

    # Final factor
    factor = part1 + 20 * part2

    return df.select(factor).to_series()