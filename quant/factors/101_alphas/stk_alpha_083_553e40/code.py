def compute_factor(df: pl.DataFrame) -> pl.Series:
    # (high - low) / (sum(close, 5) / 5)
    sum_close_5 = rolling_sum(pl.col('close'), window=5)
    hl = pl.col('high') - pl.col('low')
    inner1 = hl / (sum_close_5 / 5)
    
    # delay by 2 periods
    delayed = delay(inner1, periods=2)
    
    # rank(delay(...)) - cross-section
    rank_delayed = rank(delayed).over('date')
    
    # rank(rank(volume)) - cross-section
    rank_vol = rank(pl.col('volume')).over('date')
    rank_rank_vol = rank(rank_vol).over('date')
    
    # numerator: rank(delay) * rank(rank(volume))
    numerator = rank_delayed * rank_rank_vol
    
    # denominator: ((high - low) / (sum(close,5)/5)) / (vwap - close)
    vwap_close_diff = pl.col('vwap') - pl.col('close')
    denominator = inner1 / vwap_close_diff
    
    # final factor
    factor = numerator / denominator
    
    return df.select(factor).to_series()