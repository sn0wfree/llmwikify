def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Materialize the rolling sum expression first (time-series result)
    # before applying cross-sectional rank, to avoid re-evaluation within date groups
    df = df.with_columns(
        ((rolling_sum(pl.col('returns'), window=240) - rolling_sum(pl.col('returns'), window=20)) / 220).alias('_sum_diff')
    )
    
    # Compute the factor
    # Part 1: (-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)
    part1 = (-1 * ts_min(pl.col('low'), window=5)) + delay(ts_min(pl.col('low'), window=5), periods=5)
    
    # Part 2: cross-sectional rank of the materialized sum_diff
    part2 = rank(pl.col('_sum_diff')).over('date')
    
    # Part 3: ts_rank(volume, 5)
    part3 = ts_rank(pl.col('volume'), window=5)
    
    # Final factor
    factor = part1 * part2 * part3
    
    return df.select(factor).to_series()