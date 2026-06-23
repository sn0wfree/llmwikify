def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    close = pl.col('close')

    # Delayed close values
    close_1 = delay(close, periods=1)
    close_10 = delay(close, periods=10)
    close_20 = delay(close, periods=20)

    # Two parts of the condition
    part_a = (close_20 - close_10) / 10
    part_b = (close_10 - close) / 10

    # Condition: (part_a - part_b) < -0.1
    cond = (part_a - part_b) < -0.1

    # If condition true -> 1, else -> -1 * (close - delay(close, 1))
    factor = pl.when(cond).then(1).otherwise(-1 * (close - close_1))

    return df.select(factor).to_series()