def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date) — do NOT re-sort

    # Inner term: ((close - low) - (high - close)) / (high - low) * volume
    inner = (
        ((pl.col('close') - pl.col('low')) - (pl.col('high') - pl.col('close')))
        / (pl.col('high') - pl.col('low'))
        * pl.col('volume')
    )

    # rank(inner) cross-sectionally, then scale
    scaled_rank_inner = scale(rank(inner).over('date')).over('date')

    # ts_argmax(close, 10) — per code (df already sorted)
    argmax_close = ts_argmax(pl.col('close'), window=10)

    # rank(argmax) cross-sectionally, then scale
    scaled_rank_argmax = scale(rank(argmax_close).over('date')).over('date')

    # Final: 0 - (1 * (2 * scaled_rank_inner - scaled_rank_argmax))
    factor = -(2 * scaled_rank_inner - scaled_rank_argmax)

    return df.select(factor).to_series()