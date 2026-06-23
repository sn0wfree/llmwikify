def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv10: rolling mean of volume with window 10
    adv10 = rolling_mean(pl.col('volume'), window=10)
    
    # sum(adv10, 49.6054) -> window 50
    sum_adv10 = rolling_sum(adv10, window=50)
    
    # correlation(vwap, sum_adv10, 8.47743) -> window 8
    corr1 = rolling_corr(pl.col('vwap'), sum_adv10, window=8)
    
    # rank(correlation)
    rank_corr1 = rank(corr1).over('date')
    
    # power 4
    powered = rank_corr1 ** 4
    
    # rank again
    rank_pow = rank(powered).over('date')
    
    # Log(product(rank_pow, 14.9655)) -> window 15
    # Use identity: Log(product(x, n)) = sum(log(x), n)  (since product = exp(sum(log)))
    # Add small epsilon to avoid log(0)
    logged_sum = ts_sum((rank_pow + 1e-10).log(), window=15)
    
    # rank of the logged sum
    left = rank(logged_sum).over('date')
    
    # Right side: rank(correlation(rank(vwap), rank(volume), 5.07914)) -> window 5
    rank_vwap = rank(pl.col('vwap')).over('date')
    rank_vol = rank(pl.col('volume')).over('date')
    corr2 = rolling_corr(rank_vwap, rank_vol, window=5)
    right = rank(corr2).over('date')
    
    # Final: (left < right) * -1
    final = pl.when(left < right).then(-1).otherwise(0)
    
    return df.select(final.alias('factor')).to_series()