def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Cross-sectional rank of volume per date
    rank_vol = rank(pl.col('volume')).over('date')

    # 5-day rolling correlation between high and rank(volume)
    corr = correlation(pl.col('high'), rank_vol, window=5)

    # Multiply by -1
    factor = -1 * corr

    return df.select(factor).to_series()