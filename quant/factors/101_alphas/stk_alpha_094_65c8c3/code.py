def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv60 = 60-day average daily volume
    adv60 = ts_mean(pl.col('volume'), 60)

    # ts_min(vwap, 11.5783) -> rolling_min, window must be int
    vwap_min = rolling_min(pl.col('vwap'), window=11)

    # rank(vwap - ts_min(vwap, 11.5783)) -- cross-sectional rank per date
    rank_part = rank(pl.col('vwap') - vwap_min).over('date')

    # Ts_Rank(vwap, 19.6462) -> cast to int
    ts_rank_vwap = ts_rank(pl.col('vwap'), 19)

    # Ts_Rank(adv60, 4.02992) -> cast to int
    ts_rank_adv60 = ts_rank(adv60, 4)

    # correlation(Ts_Rank(vwap, 19.6462), Ts_Rank(adv60, 4.02992), 18.0926) -> int
    corr = rolling_corr(ts_rank_vwap, ts_rank_adv60, 18)

    # Ts_Rank(correlation(...), 2.70756) -> cast to int
    ts_rank_corr = ts_rank(corr, 2)

    # (rank_part ^ ts_rank_corr) * -1
    factor = (rank_part ** ts_rank_corr) * -1

    return df.select(factor).to_series()