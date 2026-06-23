def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20: 20-day rolling mean of volume (per code)
    adv20 = rolling_mean(pl.col('volume'), window=20)

    # Inner expression: ((-1 * returns) * adv20) * vwap * (high - close)
    inner = (-1 * pl.col('returns')) * adv20 * pl.col('vwap') * (pl.col('high') - pl.col('close'))

    # Cross-sectional rank per date
    factor = rank(inner).over('date')

    return df.select(factor).to_series()