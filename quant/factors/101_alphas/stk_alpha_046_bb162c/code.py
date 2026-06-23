def compute_factor(df: pl.DataFrame) -> pl.Series:
    close = pl.col('close')
    
    delay_20 = delay(close, periods=20)
    delay_10 = delay(close, periods=10)
    delay_1 = delay(close, periods=1)
    
    term1 = (delay_20 - delay_10) / 10
    term2 = (delay_10 - close) / 10
    term = term1 - term2
    
    factor = pl.when(term > 0.25).then(-1).otherwise(
        pl.when(term < 0).then(1).otherwise(-1 * (close - delay_1))
    )
    
    return df.select(factor).to_series()