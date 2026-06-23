def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Sort by (code, date) for per-code rolling operations
    df = df.sort(['code', 'date'])

    # Step 1: sum(close, 100) / 100  (equivalent to rolling_mean)
    mean_close_100 = rolling_mean(pl.col('close'), window=100)

    # Step 2: delta(mean_close_100, 100)
    delta_mean = delta(mean_close_100, periods=100)

    # Step 3: delay(close, 100)
    delay_close = delay(pl.col('close'), periods=100)

    # Step 4: ratio = delta_mean / delay_close
    ratio = delta_mean / delay_close

    # Step 5: condition (ratio < 0.05) || (ratio == 0.05)  ->  ratio <= 0.05
    cond = (ratio <= 0.05)

    # Branch 1: -1 * (close - ts_min(close, 100))
    branch1 = -1 * (pl.col('close') - ts_min(pl.col('close'), window=100))

    # Branch 2: -1 * delta(close, 3)
    branch2 = -1 * delta(pl.col('close'), periods=3)

    # Select branch based on condition
    factor = pl.when(cond).then(branch1).otherwise(branch2)

    return df.select(factor).to_series()