def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv10: 10-day rolling mean of volume (proxy for average dollar volume)
    adv10 = rolling_mean(pl.col('volume'), window=10)
    
    # Part 1:
    # low * 0.967285 + low * (1 - 0.967285)  (algebraically = low, but compute as given)
    low_expr = pl.col('low') * 0.967285 + pl.col('low') * (1 - 0.967285)
    # 6-day rolling correlation between low_expr and adv10
    corr = rolling_corr(low_expr, adv10, window=6)
    # Decay linear with period 5
    decayed = decay_linear(corr, period=5)
    # 3-day ts_rank
    part1 = ts_rank(decayed, window=3)
    
    # Part 2:
    # IndNeutralize(vwap, IndClass.industry) - simplified to vwap (no industry column)
    vwap_neutral = pl.col('vwap')
    # Delta with 3 periods
    vwap_delta = delta(vwap_neutral, periods=3)
    # Decay linear with period 10
    vwap_decayed = decay_linear(vwap_delta, period=10)
    # 15-day ts_rank
    part2 = ts_rank(vwap_decayed, window=15)
    
    # Final factor: part1 - part2
    factor = part1 - part2
    
    return df.select(factor).to_series()