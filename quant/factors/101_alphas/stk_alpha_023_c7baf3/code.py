def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Rolling mean of high over 20 days
    high_mean = rolling_mean(pl.col('high'), window=20)

    # 2-period delta of high
    high_delta = delta(pl.col('high'), periods=2)

    # Conditional: if rolling_mean(high, 20) < high, then -delta(high, 2), else 0
    factor = pl.when(high_mean < pl.col('high')).then(-high_delta).otherwise(0)

    return df.select(factor).to_series()