def compute_factor(df: pl.DataFrame) -> pl.Series:
    # delay(close, 5) - delay close by 5 periods
    close_delayed = delay(pl.col('close'), periods=5)
    
    # sum(delay(close, 5), 20) / 20
    avg_delayed = rolling_sum(close_delayed, window=20) / 20
    
    # rank(sum(delay(close, 5), 20) / 20)
    rank_avg = rank(avg_delayed).over('date')
    
    # correlation(close, volume, 2)
    corr_cv = rolling_corr(pl.col('close'), pl.col('volume'), window=2)
    
    # sum(close, 5)
    sum_close_5 = rolling_sum(pl.col('close'), window=5)
    
    # sum(close, 20)
    sum_close_20 = rolling_sum(pl.col('close'), window=20)
    
    # correlation(sum(close, 5), sum(close, 20), 2)
    corr_sums = rolling_corr(sum_close_5, sum_close_20, window=2)
    
    # rank(correlation(sum(close, 5), sum(close, 20), 2))
    rank_corr_sums = rank(corr_sums).over('date')
    
    # -1 * rank(...) * correlation(...) * rank(...)
    factor = -1 * rank_avg * corr_cv * rank_corr_sums
    
    return df.select(factor).to_series()