def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 1. delta of log(volume) with period 2
    log_vol = pl.col('volume').log()
    delta_log_vol = delta(log_vol, periods=2)

    # 2. cross-section rank of delta_log_vol
    rank1 = rank(delta_log_vol).over('date')

    # 3. (close - open) / open
    price_change = (pl.col('close') - pl.col('open')) / pl.col('open')

    # 4. cross-section rank of price change
    rank2 = rank(price_change).over('date')

    # 5. 6-period rolling correlation between the two ranked series
    corr = correlation(rank1, rank2, window=6)

    # 6. negate
    factor = -1 * corr

    return df.select(factor).to_series()