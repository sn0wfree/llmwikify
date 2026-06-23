def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Inner: sum(returns, 2) - 2-period rolling sum of returns
    sum_ret_2 = rolling_sum(pl.col('returns'), window=2)
    
    # Outer: sum(sum(returns, 2), 3) - 3-period rolling sum of the above
    sum_sum_ret_2_3 = rolling_sum(sum_ret_2, window=3)
    
    # Ratio: sum(returns, 10) / sum(sum(returns, 2), 3)
    ratio = rolling_sum(pl.col('returns'), window=10) / sum_sum_ret_2_3
    
    # Cross-sectional rank of the ratio
    rank_ratio = rank(ratio).over('date')
    
    # returns * cap (using vwap as proxy since cap is not in the schema)
    ret_cap = pl.col('returns') * pl.col('vwap')
    
    # Cross-sectional rank of returns*cap
    rank_ret_cap = rank(ret_cap).over('date')
    
    # Final factor: -(rank_ratio * rank_ret_cap)
    factor = -(rank_ratio * rank_ret_cap)
    
    return df.select(factor).to_series()