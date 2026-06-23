def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date)

    # 1) delta(close, 1) — today's close minus yesterday's close
    delta_close = delta(pl.col('close'), periods=1)

    # 2) 5-day rolling min and max of delta(close, 1)
    min_delta = rolling_min(delta_close, window=5)
    max_delta = rolling_max(delta_close, window=5)

    # 3) Conditional logic from the formula:
    #    if ts_min(delta,5) > 0        -> delta(close,1)
    #    elif ts_max(delta,5) < 0      -> delta(close,1)
    #    else                          -> -1 * delta(close,1)
    factor = (
        pl.when(min_delta > 0)
        .then(delta_close)
        .otherwise(
            pl.when(max_delta < 0)
            .then(delta_close)
            .otherwise(-1 * delta_close)
        )
    )

    return df.select(factor).to_series()