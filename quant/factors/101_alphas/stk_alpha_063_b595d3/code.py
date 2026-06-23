def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date) — do NOT re-sort

    # Term 1: rank(decay_linear(delta(IndNeutralize(close, industry), 2), 8))
    # IndNeutralize requires industry classification which is unavailable; pass close through
    ind_neutral_close = pl.col('close')
    delta_close = delta(ind_neutral_close, periods=2)
    decay1 = decay_linear(delta_close, window=8)
    rank1 = rank(decay1).over('date')

    # Term 2: rank(decay_linear(corr(vwap*0.318108 + open*0.681892, sum(adv180, 37), 14), 12))
    # adv180 ~ mean(volume, 180) as proxy
    weighted_price = pl.col('vwap') * 0.318108 + pl.col('open') * (1 - 0.318108)
    adv180 = rolling_mean(pl.col('volume'), window=180)
    sum_adv = rolling_sum(adv180, window=37)
    corr_val = rolling_corr(weighted_price, sum_adv, window=14)
    decay2 = decay_linear(corr_val, window=12)
    rank2 = rank(decay2).over('date')

    # Combine: (rank1 - rank2) * -1
    factor = (rank1 - rank2) * -1

    return df.select(factor).to_series()