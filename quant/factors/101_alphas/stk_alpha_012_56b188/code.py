def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 1-period delta of volume
    vol_delta = delta(pl.col('volume'), periods=1)

    # 1-period delta of close
    close_delta = delta(pl.col('close'), periods=1)

    # sign(delta(volume, 1)) * (-1 * delta(close, 1))
    factor = vol_delta.sign() * (-1 * close_delta)

    return df.select(factor).to_series()