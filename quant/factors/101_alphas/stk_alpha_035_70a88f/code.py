def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Part 1: Ts_Rank(volume, 32)
    rank_volume = ts_rank(pl.col('volume'), window=32)

    # Part 2: 1 - Ts_Rank((close + high - low), 16)
    inner_expr = pl.col('close') + pl.col('high') - pl.col('low')
    rank_inner = ts_rank(inner_expr, window=16)

    # Part 3: 1 - Ts_Rank(returns, 32)
    rank_returns = ts_rank(pl.col('returns'), window=32)

    # Combine: part1 * part2 * part3
    factor = rank_volume * (1 - rank_inner) * (1 - rank_returns)

    return df.select(factor).to_series()