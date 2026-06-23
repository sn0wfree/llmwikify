def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Part 1: -1 * sign((close - delay(close, 7)) + delta(close, 7))
    close_delay_7 = delay(pl.col('close'), periods=7)
    close_delta_7 = delta(pl.col('close'), periods=7)
    inner = (pl.col('close') - close_delay_7) + close_delta_7
    sign_part = -1 * inner.sign()
    
    # Part 2: 1 + rank(1 + sum(returns, 250))
    # Materialize the rolling sum first to avoid cross-code contamination
    df = df.with_columns(rolling_sum(pl.col('returns'), window=250).alias('_sum_ret'))
    rank_part = 1 + rank(pl.col('_sum_ret') + 1).over('date')
    
    # Combine
    factor = sign_part * rank_part
    
    return df.select(factor).to_series()