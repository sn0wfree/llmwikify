def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Step 1: open - close
    df = df.with_columns(
        (pl.col('open') - pl.col('close')).alias('_oc')
    )
    # Step 2: delay by 1 period
    df = df.with_columns(
        delay(pl.col('_oc'), periods=1).alias('_oc_lag1')
    )
    # Step 3: materialize 200-day correlation (Rule 2)
    df = df.with_columns(
        correlation(pl.col('_oc_lag1'), pl.col('close'), window=200).alias('_corr')
    )
    # Step 4: rank the correlation cross-sectionally
    df = df.with_columns(
        rank(pl.col('_corr')).over('date').alias('_rank_corr')
    )
    # Step 5: rank (open - close) cross-sectionally
    df = df.with_columns(
        rank(pl.col('_oc')).over('date').alias('_rank_oc')
    )
    # Step 6: sum of the two ranks
    factor = pl.col('_rank_corr') + pl.col('_rank_oc')
    return df.select(factor).to_series()