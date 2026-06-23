def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Ensure proper per-code ordering for rolling/time-series ops
    df = df.sort(['code', 'date'])

    # adv40: 40-day average dollar volume (volume * close)
    adv40 = rolling_mean(pl.col('volume') * pl.col('close'), window=40)

    # IndNeutralize: industry classification not available in df columns;
    # pass adv40 through neutralize (acts as cross-sectional demean fallback)
    adv40_neut = neutralize(adv40).over('date')

    # Rolling correlation of adv40 (neutralized) with low (~5.38 -> 5)
    corr = rolling_corr(adv40_neut, pl.col('low'), window=5)

    # Ts_Rank of the correlation over ~3.22 -> 3 days
    ts_ranked = ts_rank(corr, window=3)

    # close - ts_max(close, ~4.67 -> 5)
    close_minus_max = pl.col('close') - ts_max(pl.col('close'), window=5)

    # Cross-sectional rank of (close - ts_max(close,5))
    ranked = rank(close_minus_max).over('date')

    # Raise the ranked series to the power of ts_ranked
    powered = ranked ** ts_ranked

    # Multiply by -1
    factor = powered * -1

    return df.select(factor).to_series()