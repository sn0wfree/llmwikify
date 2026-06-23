def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Cross-sectional ranks per date
    ranked_open = rank(pl.col('open')).over('date')
    ranked_volume = rank(pl.col('volume')).over('date')

    # 10-day rolling correlation per code
    corr = rolling_corr(ranked_open, ranked_volume, window=10)

    # Negate
    factor = -1 * corr

    return df.select(factor).to_series()