def compute_factor(df: pl.DataFrame) -> pl.Series:
    diff = pl.col('vwap') - pl.col('close')
    summ = pl.col('vwap') + pl.col('close')

    factor = rank(diff).over('date') / rank(summ).over('date')

    return df.select(factor).to_series()