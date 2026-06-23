def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Part 1: (rank(1/close) * volume) / adv20
    inv_close = 1.0 / pl.col('close')
    rank_inv_close = rank(inv_close).over('date')
    part1_inner = rank_inv_close * pl.col('volume')
    adv20 = rolling_mean(pl.col('volume'), window=20)
    part1 = part1_inner / adv20
    
    # Part 2: (high * rank(high - close)) / (sum(high, 5) / 5)
    high_close_diff = pl.col('high') - pl.col('close')
    rank_hcd = rank(high_close_diff).over('date')
    high_rank = pl.col('high') * rank_hcd
    sum_high_5 = rolling_mean(pl.col('high'), window=5)  # sum(high, 5) / 5
    part2 = high_rank / sum_high_5
    
    # Combined first part
    combined = part1 * part2
    
    # Part 3: rank(vwap - delay(vwap, 5))
    vwap_delay = delay(pl.col('vwap'), periods=5)
    vwap_diff = pl.col('vwap') - vwap_delay
    rank_vwap = rank(vwap_diff).over('date')
    
    # Final
    factor = combined - rank_vwap
    
    return df.select(factor).to_series()