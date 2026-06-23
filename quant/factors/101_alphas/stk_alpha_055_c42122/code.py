def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Inner term: (close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12))
    min_low = ts_min(pl.col('low'), window=12)
    max_high = ts_max(pl.col('high'), window=12)
    inner = (pl.col('close') - min_low) / (max_high - min_low)

    # Cross-sectional rank of the inner term
    rank_inner = rank(inner).over('date')

    # Cross-sectional rank of volume
    rank_volume = rank(pl.col('volume')).over('date')

    # Rolling correlation (window=6) between the two ranked series
    corr = rolling_corr(rank_inner, rank_volume, window=6)

    # Multiply by -1
    factor = -1 * corr

    return df.select(factor).to_series()