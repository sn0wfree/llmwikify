def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date) - DO NOT sort again
    
    # Numerator: -1 * (low - close) * (open^5)
    low_minus_close = pl.col('low') - pl.col('close')
    open_pow5 = pl.col('open') ** 5
    numerator = -1 * low_minus_close * open_pow5
    
    # Denominator: (low - high) * (close^5)
    low_minus_high = pl.col('low') - pl.col('high')
    close_pow5 = pl.col('close') ** 5
    denominator = low_minus_high * close_pow5
    
    # Final factor
    factor = numerator / denominator
    
    return df.select(factor).to_series()