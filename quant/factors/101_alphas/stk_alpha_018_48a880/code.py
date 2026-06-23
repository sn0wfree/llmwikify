def compute_factor(df: pl.DataFrame) -> pl.Series:
    close_open = pl.col('close') - pl.col('open')
    abs_diff = close_open.abs()
    std_5 = rolling_std(abs_diff, window=5)
    corr_10 = rolling_corr(pl.col('close'), pl.col('open'), window=10)
    inner = std_5 + close_open + corr_10
    factor = -1 * rank(inner).over('date')
    return df.select(factor).to_series()