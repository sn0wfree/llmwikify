def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])
    
    # Cross-sectional ranks
    rank_high = rank(pl.col('high')).over('date')
    rank_volume = rank(pl.col('volume')).over('date')
    
    # 3-day rolling correlation between ranked high and ranked volume
    corr = rolling_corr(rank_high, rank_volume, window=3)
    
    # Cross-sectional rank of the correlation
    rank_corr = rank(corr).over('date')
    
    # 3-day rolling sum of the ranked correlation
    sum_corr = ts_sum(rank_corr, window=3)
    
    # Multiply by -1
    factor = -1 * sum_corr
    
    return df.select(factor).to_series()