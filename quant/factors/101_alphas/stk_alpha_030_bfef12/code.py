def compute_factor(df: pl.DataFrame) -> pl.Series:
    close = pl.col('close')

    delay1 = delay(close, periods=1)
    delay2 = delay(close, periods=2)
    delay3 = delay(close, periods=3)

    sign1 = (close - delay1).sign()
    sign2 = (delay1 - delay2).sign()
    sign3 = (delay2 - delay3).sign()

    sign_sum = sign1 + sign2 + sign3

    ranked = rank(sign_sum).over('date')
    one_minus_rank = 1.0 - ranked

    vol_5 = rolling_sum(pl.col('volume'), window=5)
    vol_20 = rolling_sum(pl.col('volume'), window=20)

    factor = (one_minus_rank * vol_5) / vol_20

    return df.select(factor).to_series()