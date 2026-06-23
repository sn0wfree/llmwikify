def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 3-period delta of returns
    delta_ret = delta(pl.col('returns'), periods=3)

    # Cross-sectional rank
    ranked = rank(delta_ret).over('date')

    # Negate
    neg_ranked = -1 * ranked

    # 10-period rolling correlation between open and volume
    corr = correlation(pl.col('open'), pl.col('volume'), window=10)

    # Final factor: (-1 * rank(delta(returns, 3))) * correlation(open, volume, 10)
    factor = neg_ranked * corr

    return df.select(factor).to_series()