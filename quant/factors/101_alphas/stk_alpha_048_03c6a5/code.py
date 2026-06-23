def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date) - DO NOT call df.sort(...)

    # delta(close, 1): today's close - yesterday's close
    delta_close = delta(pl.col('close'), periods=1)

    # delay(close, 1): yesterday's close
    delay_close = delay(pl.col('close'), periods=1)

    # delta(delay(close, 1), 1): yesterday's close - two-days-ago's close
    delta_delay_close = delta(delay_close, periods=1)

    # 250-day rolling correlation between today's change and yesterday's change
    corr = correlation(delta_close, delta_delay_close, window=250)

    # (correlation * delta(close, 1)) / close
    numerator_expr = (corr * delta_close) / pl.col('close')

    # Cross-sectional neutralize (substitute for indneutralize, which requires IndClass)
    neutralized = neutralize(numerator_expr).over('date')

    # (delta(close, 1) / delay(close, 1))^2 -> daily return squared
    daily_return_sq = (delta_close / delay_close) ** 2

    # 250-day rolling sum of squared daily returns
    denom = rolling_sum(daily_return_sq, window=250)

    # Final factor: neutralized numerator / denominator
    factor = neutralized / denom

    return df.select(factor).to_series()