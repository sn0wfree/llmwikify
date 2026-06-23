def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv50: 50-day average dollar volume (close * volume)
    adv50 = ts_mean(pl.col('close') * pl.col('volume'), window=50)

    # Industry neutralize close (using neutralize as substitute since industry class unavailable)
    ind_neutral_close = neutralize(pl.col('close')).over('date')

    # Correlation between ind-neutralized close and adv50
    corr = rolling_corr(ind_neutral_close, adv50, window=18)

    # Ts_Rank of correlation
    ts_rank_corr = ts_rank(corr, window=18)

    # Delta of vwap
    vwap_delta = delta(pl.col('vwap'), periods=1)

    # Cross-sectional rank of delta(vwap)
    rank_delta = rank(vwap_delta).over('date')

    # Raise rank to the power of ts_rank
    factor = rank_delta ** ts_rank_corr

    # Multiply by -1
    factor = factor * -1

    return df.select(factor).to_series()