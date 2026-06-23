def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Materialize ts_min(vwap, 16) - convert float window to int
    df = df.with_columns(ts_min(pl.col('vwap'), window=16).alias('_ts_min_vwap'))
    # First component: vwap - ts_min(vwap, 16)
    df = df.with_columns((pl.col('vwap') - pl.col('_ts_min_vwap')).alias('_diff'))
    # Materialize adv180 = rolling mean of volume over 180 days
    df = df.with_columns(rolling_mean(pl.col('volume'), window=180).alias('_adv180'))
    # Materialize rolling correlation between vwap and adv180
    df = df.with_columns(rolling_corr(pl.col('vwap'), pl.col('_adv180'), window=18).alias('_corr'))
    # Cross-sectional ranks for both components
    df = df.with_columns([
        rank(pl.col('_diff')).over('date').alias('_rank1'),
        rank(pl.col('_corr')).over('date').alias('_rank2')
    ])
    # Compare: rank(diff) < rank(corr) -> cast to float factor
    factor = (pl.col('_rank1') < pl.col('_rank2')).cast(pl.Float32)
    return df.select(factor).to_series()