def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20 = average daily volume over the past 20 days
    adv20 = ts_mean(pl.col('volume'), window=20)
    
    # sum(adv20, 22.4101) -> window 22
    sum_adv20 = rolling_sum(adv20, window=22)
    
    # correlation(vwap, sum(adv20), 9.91009) -> window 9
    corr = rolling_corr(pl.col('vwap'), sum_adv20, window=9)
    
    # rank of the correlation (cross-sectional)
    rank_corr = rank(corr).over('date')
    
    # (high + low) / 2
    mid = (pl.col('high') + pl.col('low')) / 2
    
    # Cross-sectional ranks
    rank_open = rank(pl.col('open')).over('date')
    rank_mid = rank(mid).over('date')
    rank_high = rank(pl.col('high')).over('date')
    
    # Inner boolean: (rank(open) + rank(open)) < (rank(mid) + rank(high))
    cond = (rank_open + rank_open) < (rank_mid + rank_high)
    
    # Cross-sectional rank of the boolean (cast to int for safety)
    rank_cond = rank(cond.cast(pl.Int32)).over('date')
    
    # Final: (rank_corr < rank_cond) * -1
    factor = ((rank_corr < rank_cond).cast(pl.Int32) * -1).cast(pl.Float64)
    
    return df.select(factor).to_series()