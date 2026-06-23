def compute_factor(df: pl.DataFrame) -> pl.Series:
    inner = 1 - (pl.col('open') / pl.col('close'))
    signed = -1 * (inner ** 1)
    factor = rank(signed).over('date')
    return df.select(factor).to_series()