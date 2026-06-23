def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Cross-sectional ranks per date
    rank_close = rank(pl.col('close')).over('date')
    rank_volume = rank(pl.col('volume')).over('date')

    # Per-code rolling covariance with window 5
    # df is already (code, date) sorted, no .over('code') needed
    cov_5 = covariance(rank_close, rank_volume, window=5)

    # Cross-sectional rank of the covariance, then negate
    factor = -1 * rank(cov_5).over('date')

    return df.select(factor).to_series()