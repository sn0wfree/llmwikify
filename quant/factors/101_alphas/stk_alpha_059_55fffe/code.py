def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Step 1: vwap blend (vwap * 0.728317 + vwap * (1 - 0.728317) = vwap)
    vwap_blend = (pl.col('vwap') * 0.728317) + (pl.col('vwap') * (1 - 0.728317))
    
    # Step 2: Industry neutralize -> use cross-sectional neutralize as fallback
    neutralized = neutralize(vwap_blend).over('date')
    
    # Step 3: Rolling correlation with volume, window = 4
    corr = rolling_corr(neutralized, pl.col('volume'), window=4)
    
    # Step 4: Decay linear, window = 16
    decayed = decay_linear(corr, window=16)
    
    # Step 5: Ts_Rank, window = 8
    ts_ranked = ts_rank(decayed, window=8)
    
    # Step 6: Multiply by -1
    factor = -1 * ts_ranked
    
    return df.select(factor).to_series()