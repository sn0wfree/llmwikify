def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date) — do not re-sort

    # ADV20: 20-day average of volume
    adv20 = ts_mean(pl.col('volume'), 20)

    # 5-day rolling correlation between ADV20 and low
    corr = correlation(adv20, pl.col('low'), 5)

    # (high + low) / 2  — mid price
    mid_price = (pl.col('high') + pl.col('low')) / 2

    # Combine: correlation + mid_price - close
    expr = corr + mid_price - pl.col('close')

    # Cross-sectional scale (preserves sign, normalizes by sum of |x|)
    factor = scale(expr).over('date')

    return df.select(factor).to_series()