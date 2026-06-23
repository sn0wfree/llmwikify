def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv81: 81-day rolling average of volume
    adv81 = rolling_mean(pl.col('volume'), window=81)

    # ---- Part A: rank(decay_linear(delta(close*0.369701 + vwap*0.630299, 1.91233), 2.65461))
    inner_a = pl.col('close') * 0.369701 + pl.col('vwap') * (1 - 0.369701)
    delta_a = delta(inner_a, periods=round(1.91233))
    decay_a = decay_linear(delta_a, window=round(2.65461))
    rank_a = rank(decay_a).over('date')

    # ---- Part B: Ts_Rank(decay_linear(abs(correlation(Neutralize(adv81), close, 13.4132)), 4.89768), 14.4535)
    # Use neutralize as cross-sectional substitute for indneutralize (no industry column available)
    neut_adv81 = neutralize(adv81).over('date')
    corr_b = correlation(neut_adv81, pl.col('close'), window=round(13.4132))
    abs_corr = corr_b.abs()
    decay_b = decay_linear(abs_corr, window=round(4.89768))
    ts_rank_b = ts_rank(decay_b, window=round(14.4535))

    # max(rank_a, ts_rank_b) * -1
    factor = pl.max_horizontal(rank_a, ts_rank_b) * -1

    return df.select(factor).to_series()