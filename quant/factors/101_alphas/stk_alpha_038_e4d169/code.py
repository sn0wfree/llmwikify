def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Ts_Rank(close, 10) - time-series rank over 10-day window
    ts_rank_close = ts_rank(pl.col('close'), window=10)
    
    # Cross-section rank of Ts_Rank
    rank1 = rank(ts_rank_close).over('date')
    
    # Close to open ratio
    ratio = pl.col('close') / pl.col('open')
    
    # Cross-section rank of close/open
    rank2 = rank(ratio).over('date')
    
    # Final factor: (-1 * rank1) * rank2
    factor = (-1 * rank1) * rank2
    
    return df.select(factor).to_series()