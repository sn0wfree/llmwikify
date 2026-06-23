def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Cross-sectional differences using delayed (lagged) values
    open_minus_high = pl.col('open') - delay(pl.col('high'), periods=1)
    open_minus_close = pl.col('open') - delay(pl.col('close'), periods=1)
    open_minus_low = pl.col('open') - delay(pl.col('low'), periods=1)

    # Cross-sectional rank per date for each term
    rank1 = rank(open_minus_high).over('date')
    rank2 = rank(open_minus_close).over('date')
    rank3 = rank(open_minus_low).over('date')

    # Combine: -1 * rank1 * rank2 * rank3
    factor = -1 * rank1 * rank2 * rank3

    return df.select(factor).to_series()