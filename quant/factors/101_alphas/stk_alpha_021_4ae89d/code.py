def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 8-day and 2-day moving averages of close
    ma8 = rolling_mean(pl.col('close'), window=8)
    ma2 = rolling_mean(pl.col('close'), window=2)

    # 8-day rolling stddev of close
    std8 = rolling_std(pl.col('close'), window=8)

    # 20-day average volume (adv20)
    adv20 = rolling_mean(pl.col('volume'), window=20)

    # Nested conditional logic
    cond1 = (ma8 + std8) < ma2
    cond2 = ma2 < (ma8 - std8)
    cond3 = (pl.col('volume') / adv20) >= 1  # (1 < vol/adv20) || (vol/adv20 == 1)

    factor = (
        pl.when(cond1)
        .then(-1)
        .otherwise(
            pl.when(cond2)
            .then(1)
            .otherwise(
                pl.when(cond3).then(1).otherwise(-1)
            )
        )
    )

    return df.select(factor).to_series()