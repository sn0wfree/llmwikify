def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv60: 60-day average daily volume
    adv60 = ts_mean(pl.col('volume'), window=60)

    # --- Inner expression 1 ---
    # Weighted combination of low and vwap
    weighted = (pl.col('low') * 0.721001) + (pl.col('vwap') * (1 - 0.721001))

    # Industry neutralize substitute (cross-sectional neutralize since no industry col)
    ind_neutralized = neutralize(weighted).over('date')

    # delta with period 3 (floor of 3.3705)
    delta_val = delta(ind_neutralized, periods=3)

    # decay_linear with window 20 (floor of 20.4523)
    decayed1 = decay_linear(delta_val, window=20)

    # cross-sectional rank
    ranked = rank(decayed1).over('date')

    # --- Inner expression 2 ---
    # Ts_Rank of low with window 7 (floor of 7.87871)
    ts_rank_low = ts_rank(pl.col('low'), window=7)

    # Ts_Rank of adv60 with window 17 (floor of 17.255)
    ts_rank_adv = ts_rank(adv60, window=17)

    # correlation between the two ts_ranks with window 4 (floor of 4.97547)
    corr_val = ts_corr(ts_rank_low, ts_rank_adv, window=4)

    # Ts_Rank of correlation with window 18 (floor of 18.5925)
    ts_rank_corr = ts_rank(corr_val, window=18)

    # decay_linear with window 15 (floor of 15.7152)
    decayed2 = decay_linear(ts_rank_corr, window=15)

    # Ts_Rank of decay_linear with window 6 (floor of 6.71659)
    ts_rank_decayed = ts_rank(decayed2, window=6)

    # --- Final expression ---
    factor = (ranked - ts_rank_decayed) * -1

    return df.select(factor).to_series()