def compute_factor(df: pl.DataFrame) -> pl.Series:
    factor = -1 * correlation(pl.col('open'), pl.col('volume'), window=10)
    return df.select(factor).to_series()