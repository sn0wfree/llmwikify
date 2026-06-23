def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # Cross-sectional ranks
    rank_high = rank(pl.col('high')).over('date')
    rank_volume = rank(pl.col('volume')).over('date')

    # Rolling covariance (time-series) of the two ranked series, window=5
    cov = rolling_cov(rank_high, rank_volume, window=5)

    # Cross-sectional rank of the covariance, then negate
    factor = -1 * rank(cov).over('date')

    return df.select(factor).to_series()