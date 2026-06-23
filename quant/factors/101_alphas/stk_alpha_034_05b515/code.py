def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Time-series operators (df already sorted by code, date)
    std_2 = rolling_std(pl.col('returns'), window=2)
    std_5 = rolling_std(pl.col('returns'), window=5)

    # Ratio of short-term to medium-term return volatility
    ratio = std_2 / std_5

    # Cross-sectional rank of the ratio
    rank_ratio = rank(ratio).over('date')

    # Delta of close over 1 period, cross-sectionally ranked
    rank_delta = rank(delta(pl.col('close'), periods=1)).over('date')

    # Combine: (1 - rank(ratio)) + (1 - rank(delta))
    inner = (1 - rank_ratio) + (1 - rank_delta)

    # Final cross-sectional rank
    factor = rank(inner).over('date')

    return df.select(factor).to_series()