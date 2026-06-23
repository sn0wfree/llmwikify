def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # Step 1: ts_max(vwap, 15.3217) — window truncated to 15
    vwap_max = ts_max(pl.col('vwap'), window=15)

    # Step 2: vwap - ts_max(vwap, 15)
    diff_vwap = pl.col('vwap') - vwap_max

    # Step 3: Ts_Rank(..., 20.7127) — window truncated to 20
    ts_rank_val = ts_rank(diff_vwap, window=20)

    # Step 4: delta(close, 4.96796) — periods truncated to 4
    close_delta = delta(pl.col('close'), periods=4)

    # Step 5: SignedPower(x, y) = sign(x) * |x|^y
    signed_power = ts_rank_val.sign() * (ts_rank_val.abs() ** close_delta)

    return df.select(signed_power).to_series()