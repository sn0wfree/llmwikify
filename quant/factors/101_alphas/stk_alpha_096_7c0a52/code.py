def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Step 1: compute adv60 and basic ranks
    df = df.with_columns(
        adv60=rolling_mean(pl.col('volume'), window=60),
        rank_vwap=rank(pl.col('vwap')).over('date'),
        rank_volume=rank(pl.col('volume')).over('date'),
    )
    
    # Step 2: First branch - correlation of ranks
    df = df.with_columns(
        corr1=rolling_corr(pl.col('rank_vwap'), pl.col('rank_volume'), window=4)
    )
    df = df.with_columns(
        decay1=decay_linear(pl.col('corr1'), 4)
    )
    df = df.with_columns(
        ts_rank1=ts_rank(pl.col('decay1'), 8)
    )
    
    # Step 3: Second branch - ts_rank of close and adv60
    df = df.with_columns(
        ts_rank_close=ts_rank(pl.col('close'), 7),
        ts_rank_adv60=ts_rank(pl.col('adv60'), 4),
    )
    df = df.with_columns(
        corr2=rolling_corr(pl.col('ts_rank_close'), pl.col('ts_rank_adv60'), window=4)
    )
    df = df.with_columns(
        ts_argmax2=ts_argmax(pl.col('corr2'), 13)
    )
    df = df.with_columns(
        decay2=decay_linear(pl.col('ts_argmax2'), 14),
        ts_rank2=ts_rank(pl.col('ts_argmax2'), 13)
    )
    
    # Final: max(...) * -1
    factor = pl.max_horizontal(pl.col('ts_rank1'), pl.col('ts_rank2')) * -1
    
    return df.select(factor).to_series()