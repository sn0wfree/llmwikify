def compute_factor(df: pl.DataFrame) -> pl.Series:
    factor = (pl.col('high') * pl.col('low')) ** 0.5 - pl.col('vwap')
    return df.select(factor).to_series()