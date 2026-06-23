def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])
    
    # Part 1: rank(decay_linear(delta(vwap, 3.51013), 7.23052))
    delta_vwap = delta(pl.col('vwap'), periods=int(3.51013))
    decay1 = decay_linear(delta_vwap, window=int(7.23052))
    rank1 = rank(decay1).over('date')
    
    # Part 2: Ts_Rank(decay_linear((((low*0.96633 + low*(1-0.96633)) - vwap) / (open - (high+low)/2)), 11.4157), 6.72611)
    inner = (
        ((pl.col('low') * 0.96633) + (pl.col('low') * (1 - 0.96633)) - pl.col('vwap')) /
        (pl.col('open') - ((pl.col('high') + pl.col('low')) / 2))
    )
    decay2 = decay_linear(inner, window=int(11.4157))
    ts_rank1 = ts_rank(decay2, window=int(6.72611))
    
    # Combine and multiply by -1
    factor = (rank1 + ts_rank1) * -1
    
    return df.select(factor).to_series()