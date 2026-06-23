def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Inner: if returns < 0 then stddev(returns, 20) else close
    inner = pl.when(pl.col('returns') < 0).then(
        rolling_std(pl.col('returns'), window=20)
    ).otherwise(pl.col('close'))

    # SignedPower: sign(x) * abs(x)^2
    signed = inner.sign() * (inner.abs() ** 2)

    # Ts_ArgMax with 5-day window
    argmax = ts_argmax(signed, window=5)

    # Cross-sectional rank, centred around zero
    factor = rank(argmax).over('date') - 0.5

    return df.select(factor).to_series()