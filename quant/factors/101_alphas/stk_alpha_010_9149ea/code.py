def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 1. Sort by (code, date) for per-code rolling
    df = df.sort(['code', 'date'])

    # 2. 1-period delta of close
    delta_close = delta(pl.col('close'), periods=1)

    # 3. 4-period rolling min and max of delta
    min_delta = ts_min(delta_close, window=4)
    max_delta = ts_max(delta_close, window=4)

    # 4. Conditional logic:
    #    if ts_min(delta, 4) > 0  -> use delta
    #    elif ts_max(delta, 4) < 0 -> use delta
    #    else -> -delta
    inner = pl.when(min_delta > 0).then(delta_close).otherwise(
        pl.when(max_delta < 0).then(delta_close).otherwise(-delta_close)
    )

    # 5. Cross-sectional rank per date
    factor = rank(inner).over('date')

    return df.select(factor).to_series()