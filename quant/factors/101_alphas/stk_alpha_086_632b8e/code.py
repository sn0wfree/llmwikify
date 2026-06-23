def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20: 20-day rolling mean of volume
    adv20 = rolling_mean(pl.col('volume'), window=20)
    
    # sum(adv20, 14.7444) -> delta(adv20, periods=15) [rounded]
    sum_adv20 = delta(adv20, periods=15)
    
    # correlation(close, sum_adv20, 6.00049) -> window=6 [rounded]
    corr_expr = correlation(pl.col('close'), sum_adv20, window=6)
    
    # Ts_Rank(corr_expr, 20.4195) -> window=20 [rounded]
    ts_rank_expr = ts_rank(corr_expr, window=20)
    
    # Materialize the time-series result before cross-section comparison
    df = df.with_columns(ts_rank_expr.alias('_ts_rank'))
    
    # rank(((open + close) - (vwap + open))) = rank(close - vwap)
    rank_expr = rank(pl.col('close') - pl.col('vwap')).over('date')
    
    # (ts_rank < rank) * -1
    factor = (pl.col('_ts_rank') < rank_expr) * -1
    
    return df.select(factor).to_series()