def compute_factor(df: pl.DataFrame) -> pl.Series:
    # correlation(high, volume, 5) - rolling correlation per code
    corr_hv = correlation(pl.col('high'), pl.col('volume'), window=5)

    # delta(correlation(...), 5)
    delta_corr = delta(corr_hv, periods=5)

    # stddev(close, 20) - rolling std per code
    std_close = rolling_std(pl.col('close'), window=20)

    # rank(stddev(close, 20)) - cross-sectional rank per date
    rank_std = rank(std_close).over('date')

    # (-1) * (delta_corr * rank_std)
    factor = -1 * (delta_corr * rank_std)

    return df.select(factor).to_series()