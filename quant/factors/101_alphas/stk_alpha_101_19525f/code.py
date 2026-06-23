def compute_factor(df: pl.DataFrame) -> pl.Series:
    factor = (pl.col('close') - pl.col('open')) / ((pl.col('high') - pl.col('low')) + 0.001)
    return df.select(factor).to_series()