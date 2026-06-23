def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Cross-sectional ranks of volume and vwap per date
    rank_volume = rank(pl.col('volume')).over('date')
    rank_vwap = rank(pl.col('vwap')).over('date')
    
    # Rolling correlation of the two ranked series with window 6
    corr = rolling_corr(rank_volume, rank_vwap, window=6)
    
    # Rolling sum of the correlation with window 2
    summed = rolling_sum(corr, window=2)
    
    # Divide by 2
    divided = summed / 2.0
    
    # Cross-sectional rank of the result per date
    ranked = rank(divided).over('date')
    
    # Conditional: if rank > 0.5 then -1 else 1
    factor = pl.when(ranked > 0.5).then(-1).otherwise(1)
    
    return df.select(factor).to_series()