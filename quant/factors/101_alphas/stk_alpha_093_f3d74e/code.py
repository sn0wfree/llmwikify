def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])
    
    # adv81: 81-day average volume (proxy for average daily volume)
    adv81 = rolling_mean(pl.col('volume'), window=81)
    
    # Numerator: Ts_Rank(decay_linear(correlation(IndNeutralize(vwap), adv81, 17), 20), 8)
    vwap_neutralized = neutralize(pl.col('vwap')).over('date')
    corr_val = rolling_corr(vwap_neutralized, adv81, window=17)
    decay1 = decay_linear(corr_val, window=20)
    num = ts_rank(decay1, window=8)
    
    # Denominator: rank(decay_linear(delta(close*0.524434 + vwap*0.475566, 3), 16))
    weighted_price = pl.col('close') * 0.524434 + pl.col('vwap') * (1 - 0.524434)
    delta_val = delta(weighted_price, periods=3)
    decay2 = decay_linear(delta_val, window=16)
    denom = rank(decay2).over('date')
    
    factor = num / denom
    
    return df.select(factor).to_series()