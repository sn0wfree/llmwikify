def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # adv40: 40-day average daily volume
    adv40 = rolling_mean(pl.col('volume'), window=40)

    # (high + low) / 2
    mid_price = (pl.col('high') + pl.col('low')) / 2

    # correlation((high+low)/2, adv40, 8.93345) -> window=9
    corr1 = rolling_corr(mid_price, adv40, window=9)

    # decay_linear with window 10.1519 -> 10
    decay1 = decay_linear(corr1, window=10)

    # cross-sectional rank of numerator
    rank1 = rank(decay1).over('date')

    # Ts_Rank(vwap, 3.72469) -> window=4
    ts_rank_vwap = ts_rank(pl.col('vwap'), window=4)

    # Ts_Rank(volume, 18.5188) -> window=19
    ts_rank_volume = ts_rank(pl.col('volume'), window=19)

    # correlation(Ts_Rank(vwap), Ts_Rank(volume), 6.86671) -> window=7
    corr2 = rolling_corr(ts_rank_vwap, ts_rank_volume, window=7)

    # decay_linear with window 2.95011 -> 3
    decay2 = decay_linear(corr2, window=3)

    # cross-sectional rank of denominator
    rank2 = rank(decay2).over('date')

    # final ratio
    factor = rank1 / rank2

    return df.select(factor).to_series()