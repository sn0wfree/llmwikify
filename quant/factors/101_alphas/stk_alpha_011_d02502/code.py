def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Data is already sorted by (code, date) — do NOT re-sort
    df = df.sort(['code', 'date'])

    # 1. vwap - close
    vwap_close_diff = pl.col('vwap') - pl.col('close')

    # 2. ts_max of (vwap - close) over 3-day window (per code)
    max_diff = ts_max(vwap_close_diff, window=3)

    # 3. ts_min of (vwap - close) over 3-day window (per code)
    min_diff = ts_min(vwap_close_diff, window=3)

    # 4. Cross-sectional rank of each
    rank_max = rank(max_diff).over('date')
    rank_min = rank(min_diff).over('date')

    # 5. Sum of the two ranks
    sum_ranks = rank_max + rank_min

    # 6. 3-period delta of volume (per code)
    vol_delta = delta(pl.col('volume'), periods=3)

    # 7. Cross-sectional rank of the volume delta
    rank_vol_delta = rank(vol_delta).over('date')

    # 8. Final factor: (rank_max + rank_min) * rank(volume delta)
    factor = sum_ranks * rank_vol_delta

    return df.select(factor).to_series()