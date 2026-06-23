def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Weighted price: open * 0.868128 + high * 0.131872
    weighted_price = (pl.col('open') * 0.868128) + (pl.col('high') * (1 - 0.868128))
    
    # Industry neutralize (use neutralize as proxy since no industry column)
    neutralized = neutralize(weighted_price)
    
    # Delta with 4 periods (from 4.04545)
    delta_val = delta(neutralized, periods=4)
    
    # Sign of delta
    signed = delta_val.sign()
    
    # Cross-sectional rank
    rank_val = rank(signed).over('date')
    
    # adv10: 10-day average daily volume
    adv10 = rolling_mean(pl.col('volume'), window=10)
    
    # Correlation between high and adv10 with window=5 (from 5.11456)
    corr = rolling_corr(pl.col('high'), adv10, window=5)
    
    # Ts_Rank with window=5 (from 5.53756)
    ts_rank_val = ts_rank(corr, window=5)
    
    # Power: rank^ts_rank, then multiply by -1
    factor = (rank_val ** ts_rank_val) * -1
    
    return df.select(factor).to_series()