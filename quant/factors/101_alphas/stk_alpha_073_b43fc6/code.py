def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date); do not re-sort

    # Part A: rank( decay_linear( delta(vwap, 4.72775), 2.91864 ) )
    vwap_delta = delta(pl.col('vwap'), periods=int(4.72775))
    vwap_decayed = decay_linear(vwap_delta, window=int(2.91864))
    part_a = rank(vwap_decayed).over('date')

    # Part B: Ts_Rank( decay_linear( (delta(w, 2.03608) / w) * -1, 3.33829 ), 16.7411 )
    # where w = open * 0.147155 + low * (1 - 0.147155)
    w = pl.col('open') * 0.147155 + pl.col('low') * (1 - 0.147155)
    w_delta = delta(w, periods=int(2.03608))
    ratio = (w_delta / w) * -1
    ratio_decayed = decay_linear(ratio, window=int(3.33829))
    part_b = ts_rank(ratio_decayed, window=int(16.7411))

    # max(Part A, Part B) * -1
    factor = pl.max_horizontal([part_a, part_b]) * -1

    return df.select(factor).to_series()