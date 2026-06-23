def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Inner expression: ((close - low) - (high - close)) / (close - low)
    close = pl.col('close')
    low = pl.col('low')
    high = pl.col('high')

    numerator = (close - low) - (high - close)
    denominator = close - low
    inner = numerator / denominator

    # Apply delta with periods=9
    d = delta(inner, periods=9)

    # Multiply by -1
    factor = -1 * d

    return df.select(factor).to_series()