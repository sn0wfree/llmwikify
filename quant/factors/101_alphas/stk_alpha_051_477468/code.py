def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Delayed close values
    close_20 = delay(pl.col('close'), periods=20)
    close_10 = delay(pl.col('close'), periods=10)
    close_1 = delay(pl.col('close'), periods=1)

    # Average 10-day return from 20 days ago to 10 days ago
    ret_past = (close_20 - close_10) / 10
    # Average 10-day return from 10 days ago to today
    ret_recent = (close_10 - pl.col('close')) / 10

    # Condition: momentum deceleration worse than -5%
    condition = (ret_past - ret_recent) < (-0.05)

    # Else branch: negative of 1-day return
    else_val = (-1) * (pl.col('close') - close_1)

    factor = pl.when(condition).then(1).otherwise(else_val)

    return df.select(factor).to_series()