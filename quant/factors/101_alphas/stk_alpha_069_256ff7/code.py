def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20: 20-day average daily volume
    adv20 = rolling_mean(pl.col('volume'), window=20)
    
    # Step 1: Industry neutralize vwap (using neutralize as proxy since no industry column)
    ind_neutral_vwap = neutralize(pl.col('vwap')).over('date')
    
    # Step 2: delta with period ~3 (rounded from 2.72412)
    delta_vwap = delta(ind_neutral_vwap, periods=3)
    
    # Step 3: ts_max with window ~5 (rounded from 4.79344)
    ts_max_delta = ts_max(delta_vwap, window=5)
    
    # Step 4: cross-sectional rank
    rank1 = rank(ts_max_delta).over('date')
    
    # Step 5: weighted close/vwap combo
    close_vwap_combo = pl.col('close') * 0.490655 + pl.col('vwap') * (1 - 0.490655)
    
    # Step 6: rolling correlation with adv20 over ~5 days (rounded from 4.92416)
    corr = rolling_corr(close_vwap_combo, adv20, window=5)
    
    # Step 7: Ts_Rank over ~9 days (rounded from 9.0615)
    ts_rank_corr = ts_rank(corr, window=9)
    
    # Step 8: rank1 ^ ts_rank_corr, then multiply by -1
    factor = (rank1 ** ts_rank_corr) * -1
    
    return df.select(factor).to_series()