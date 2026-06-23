def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Sum of open over 5 periods
    sum_open = rolling_sum(pl.col('open'), window=5)
    
    # Sum of returns over 5 periods
    sum_returns = rolling_sum(pl.col('returns'), window=5)
    
    # Product: sum(open, 5) * sum(returns, 5)
    product = sum_open * sum_returns
    
    # Delay by 10 periods
    delayed_product = delay(product, periods=10)
    
    # Difference
    diff = product - delayed_product
    
    # Cross-sectional rank, multiplied by -1
    factor = -1 * rank(diff).over('date')
    
    return df.select(factor).to_series()