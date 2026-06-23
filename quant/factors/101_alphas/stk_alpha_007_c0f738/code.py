def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv20 = 20-day average daily volume
    adv20 = rolling_mean(pl.col('volume'), window=20)

    # delta(close, 7) = close - close shifted by 7
    delta_close = delta(pl.col('close'), periods=7)

    # ts_rank(abs(delta(close, 7)), 60)
    ts_rank_val = ts_rank(delta_close.abs(), window=60)

    # sign(delta(close, 7))
    sign_val = delta_close.sign()

    # Condition: adv20 < volume
    cond = adv20 < pl.col('volume')

    # True branch: -1 * ts_rank(abs(delta(close,7)), 60) * sign(delta(close, 7))
    true_val = -1 * ts_rank_val * sign_val

    # False branch: -1
    factor = pl.when(cond).then(true_val).otherwise(-1)

    return df.select(factor).to_series()