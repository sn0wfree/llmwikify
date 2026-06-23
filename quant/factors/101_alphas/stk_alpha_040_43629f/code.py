def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date) — DO NOT re-sort
    
    # Time-series: rolling std of high with window 10
    std_high = rolling_std(pl.col('high'), window=10)
    
    # Cross-section rank of the rolling std per date
    rank_std = rank(std_high).over('date')
    
    # Time-series: rolling correlation between high and volume with window 10
    corr_hv = correlation(pl.col('high'), pl.col('volume'), window=10)
    
    # Combine: -1 * rank(stddev(high, 10)) * correlation(high, volume, 10)
    factor = -1 * rank_std * corr_hv
    
    return df.select(factor).to_series()