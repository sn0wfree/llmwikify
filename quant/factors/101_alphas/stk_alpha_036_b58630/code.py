def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Part 1: 2.21 * rank(correlation((close - open), delay(volume, 1), 15))
    df = df.with_columns(
        correlation(
            (pl.col('close') - pl.col('open')),
            delay(pl.col('volume'), periods=1),
            window=15
        ).alias('_corr1')
    )
    part1 = 2.21 * rank(pl.col('_corr1')).over('date')

    # Part 2: 0.7 * rank((open - close))
    df = df.with_columns(
        (pl.col('open') - pl.col('close')).alias('_oc')
    )
    part2 = 0.7 * rank(pl.col('_oc')).over('date')

    # Part 3: 0.73 * rank(Ts_Rank(delay((-1 * returns), 6), 5))
    df = df.with_columns(
        delay((-1 * pl.col('returns')), periods=6).alias('_neg_ret_d6')
    )
    df = df.with_columns(
        ts_rank(pl.col('_neg_ret_d6'), window=5).alias('_ts_rank1')
    )
    part3 = 0.73 * rank(pl.col('_ts_rank1')).over('date')

    # Part 4: rank(abs(correlation(vwap, adv20, 6)))
    # adv20 = 20-day average volume
    df = df.with_columns(
        rolling_mean(pl.col('volume'), window=20).alias('_adv20')
    )
    df = df.with_columns(
        correlation(
            pl.col('vwap'),
            pl.col('_adv20'),
            window=6
        ).alias('_corr2')
    )
    df = df.with_columns(
        pl.col('_corr2').abs().alias('_abs_corr2')
    )
    part4 = rank(pl.col('_abs_corr2')).over('date')

    # Part 5: 0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))
    df = df.with_columns(
        rolling_mean(pl.col('close'), window=200).alias('_close_mean200')
    )
    df = df.with_columns(
        ((pl.col('_close_mean200') - pl.col('open')) * (pl.col('close') - pl.col('open'))).alias('_term5')
    )
    part5 = 0.6 * rank(pl.col('_term5')).over('date')

    # Final factor
    factor = part1 + part2 + part3 + part4 + part5

    return df.select(factor).to_series()