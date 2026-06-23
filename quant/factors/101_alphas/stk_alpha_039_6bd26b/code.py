def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Materialize adv20 (20-day average volume)
    df = df.with_columns(
        rolling_mean(pl.col('volume'), window=20).alias('_adv20')
    )

    # Materialize decay_linear(volume/adv20, 9) - time-series
    df = df.with_columns(
        decay_linear(pl.col('volume') / pl.col('_adv20'), window=9).alias('_decay')
    )

    # Cross-section rank on materialized _decay
    df = df.with_columns(
        rank(pl.col('_decay')).over('date').alias('_rank_decay')
    )

    # delta(close, 7) * (1 - rank_decay) - both inputs are materialized
    df = df.with_columns(
        (delta(pl.col('close'), periods=7) * (1 - pl.col('_rank_decay'))).alias('_product')
    )

    # Cross-section rank of the product
    df = df.with_columns(
        rank(pl.col('_product')).over('date').alias('_rank_product')
    )

    # Materialize sum(returns, 250) - time-series
    df = df.with_columns(
        rolling_sum(pl.col('returns'), window=250).alias('_sum_ret')
    )

    # Cross-section rank of sum returns
    df = df.with_columns(
        rank(pl.col('_sum_ret')).over('date').alias('_rank_sum_ret')
    )

    # Final factor: (-1 * rank_product) * (1 + rank_sum_ret)
    factor = (-1 * pl.col('_rank_product')) * (1 + pl.col('_rank_sum_ret'))

    return df.select(factor).to_series()