def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 1. Cross-sectional rank of volume
    rank_volume = rank(pl.col('volume')).over('date')

    # 2. Cross-sectional rank of vwap
    rank_vwap = rank(pl.col('vwap')).over('date')

    # 3. Rolling correlation (window=5) between rank(volume) and rank(vwap)
    corr = correlation(rank_volume, rank_vwap, window=5)

    # 4. Cross-sectional rank of the correlation
    rank_corr = rank(corr).over('date')

    # 5. Rolling max over 5-day window
    ts_max_corr = ts_max(rank_corr, window=5)

    # 6. Multiply by -1
    factor = -1 * ts_max_corr

    return df.select(factor).to_series()