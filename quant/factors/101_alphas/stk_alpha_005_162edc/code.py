def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 10-day rolling mean of vwap (sum/10)
    vwap_mean = rolling_sum(pl.col('vwap'), window=10) / 10

    # Part A: rank(open - vwap_mean) cross-sectionally
    part_a = rank(pl.col('open') - vwap_mean).over('date')

    # Part B: -1 * abs(rank(close - vwap)) cross-sectionally
    rank_close_vwap = rank(pl.col('close') - pl.col('vwap')).over('date')
    part_b = -1 * rank_close_vwap.abs()

    # Final factor: A * B
    factor = part_a * part_b

    return df.select(factor).to_series()