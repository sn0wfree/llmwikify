def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20 = 20-day rolling mean of volume (proxy for average daily volume)
    adv20 = rolling_mean(pl.col('volume'), window=20)
    
    # ts_min(high, 2.14593) - window rounds to 2
    high_min = ts_min(pl.col('high'), window=2)
    
    # high - ts_min(high, 2)
    high_diff = pl.col('high') - high_min
    
    # Cross-sectional rank of (high - ts_min(high, 2))
    rank1 = rank(high_diff).over('date')
    
    # IndNeutralize vwap by sector, and adv20 by subindustry.
    # Since industry classification columns are not available in df,
    # we pass the values through unchanged.
    vwap_neut = pl.col('vwap')
    adv20_neut = adv20
    
    # rolling correlation between IndNeutralize(vwap) and IndNeutralize(adv20)
    # window 6.02936 rounds to 6
    corr = rolling_corr(vwap_neut, adv20_neut, window=6)
    
    # Cross-sectional rank of the correlation
    rank2 = rank(corr).over('date')
    
    # rank1^rank2 (exponentiation)
    power = rank1 ** rank2
    
    # Multiply by -1
    factor = power * -1
    
    return df.select(factor).to_series()