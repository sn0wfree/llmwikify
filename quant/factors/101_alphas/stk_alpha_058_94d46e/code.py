def compute_factor(df: pl.DataFrame) -> pl.Series:
    # IndNeutralize(vwap, IndClass.sector) - use neutralize as substitute (sector data not available)
    neutralized_vwap = neutralize(pl.col('vwap')).over('date')
    
    # correlation(neutralized_vwap, volume, 3.92795) -> window=4
    corr = rolling_corr(neutralized_vwap, pl.col('volume'), window=4)
    
    # decay_linear(corr, 7.89291) -> window=8
    decayed = decay_linear(corr, window=8)
    
    # Ts_Rank(decayed, 5.50322) -> window=6
    ts_ranked = ts_rank(decayed, window=6)
    
    # -1 * Ts_Rank(...)
    factor = -1 * ts_ranked
    
    return df.select(factor).to_series()