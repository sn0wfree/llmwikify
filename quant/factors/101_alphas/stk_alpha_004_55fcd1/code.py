def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Cross-sectional rank of low per date
    ranked_low = rank(pl.col('low')).over('date')
    
    # Time-series rank with window of 9
    ts_ranked = ts_rank(ranked_low, window=9)
    
    # Multiply by -1
    factor = -1 * ts_ranked
    
    return df.select(factor).to_series()