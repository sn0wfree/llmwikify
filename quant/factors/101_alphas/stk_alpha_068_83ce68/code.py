def compute_factor(df: pl.DataFrame) -> pl.Series:
    # adv15: 15-day average daily volume
    df = df.with_columns(
        rolling_mean(pl.col('volume'), window=15).alias('_adv15')
    )

    # Cross-sectional ranks of high and adv15 (materialized before correlation)
    df = df.with_columns(
        rank(pl.col('high')).over('date').alias('_rank_high'),
        rank(pl.col('_adv15')).over('date').alias('_rank_adv15')
    )

    # Rolling correlation between the ranks (window 8.91644 -> 9)
    df = df.with_columns(
        correlation(pl.col('_rank_high'), pl.col('_rank_adv15'), window=9).alias('_corr')
    )

    # Time-series rank of the correlation (window 13.9333 -> 14)
    df = df.with_columns(
        ts_rank(pl.col('_corr'), window=14).alias('_ts_rank_corr')
    )

    # Weighted price: 0.518371 * close + (1 - 0.518371) * low
    weighted = pl.col('close') * 0.518371 + pl.col('low') * (1 - 0.518371)

    # Delta with period 1.06157 -> 1
    df = df.with_columns(
        delta(weighted, periods=1).alias('_delta_weighted')
    )

    # Cross-sectional rank of the delta
    df = df.with_columns(
        rank(pl.col('_delta_weighted')).over('date').alias('_rank_delta')
    )

    # (ts_rank_corr < rank_delta) * -1
    cond = pl.col('_ts_rank_corr') < pl.col('_rank_delta')
    factor = cond.cast(pl.Float64) * -1.0

    return df.select(factor).to_series()