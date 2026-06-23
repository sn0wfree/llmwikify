def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv60: average daily volume over 60 days
    adv60 = rolling_mean(pl.col('volume'), window=60)
    
    # Weighted combination of open and vwap
    w_open = pl.col('open') * 0.00817205 + pl.col('vwap') * (1 - 0.00817205)
    
    # Rolling sum of adv60 with window 9 (rounded from 8.6911)
    sum_adv60 = rolling_sum(adv60, window=9)
    
    # Rolling correlation with window 6 (rounded from 6.40374)
    corr = rolling_corr(w_open, sum_adv60, window=6)
    
    # Cross-sectional rank of correlation
    rank1 = rank(corr).over('date')
    
    # ts_min of open with window 14 (rounded from 13.635)
    min_open = ts_min(pl.col('open'), window=14)
    
    # Open minus rolling min
    diff_open = pl.col('open') - min_open
    
    # Cross-sectional rank of (open - ts_min)
    rank2 = rank(diff_open).over('date')
    
    # Boolean comparison, cast to numeric, multiply by -1
    factor = (rank1 < rank2).cast(pl.Int32) * -1
    
    return df.select(factor).to_series()