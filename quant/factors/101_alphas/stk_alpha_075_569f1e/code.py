def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv50: 50-day rolling mean of volume (per code, since df is already sorted by code,date)
    adv50 = rolling_mean(pl.col('volume'), window=50)

    # First rolling correlation: vwap vs volume, window ~ 4.24304
    corr1 = rolling_corr(pl.col('vwap'), pl.col('volume'), window=4)

    # Cross-sectional rank of corr1 (per date)
    rank1 = rank(corr1).over('date')

    # Cross-sectional ranks of low and adv50 (per date)
    rank_low = rank(pl.col('low')).over('date')
    rank_adv50 = rank(adv50).over('date')

    # Second rolling correlation: rank(low) vs rank(adv50), window ~ 12.4413
    corr2 = rolling_corr(rank_low, rank_adv50, window=12)

    # Cross-sectional rank of corr2 (per date)
    rank2 = rank(corr2).over('date')

    # Boolean comparison: rank1 < rank2
    factor = rank1 < rank2

    return df.select(factor).to_series()