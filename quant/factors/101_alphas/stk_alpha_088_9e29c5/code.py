def compute_factor(df: pl.DataFrame) -> pl.Series:
    # df is already sorted by (code, date)

    # Compute adv60 = rolling mean of volume over 60 days
    adv60 = rolling_mean(pl.col('volume'), window=60)

    # Part 1: rank(decay_linear(((rank(open) + rank(low)) - (rank(high) + rank(close))), 8.06882))
    rank_open = rank(pl.col('open')).over('date')
    rank_low = rank(pl.col('low')).over('date')
    rank_high = rank(pl.col('high')).over('date')
    rank_close_cs = rank(pl.col('close')).over('date')

    diff_ranks = (rank_open + rank_low) - (rank_high + rank_close_cs)
    decay1 = decay_linear(diff_ranks, window=8)  # 8.06882 -> 8
    part1 = rank(decay1).over('date')

    # Part 2: Ts_Rank(decay_linear(correlation(Ts_Rank(close, 8.44728), Ts_Rank(adv60, 20.6966), 8.01266), 6.65053), 2.61957)
    ts_rank_close = ts_rank(pl.col('close'), window=8)  # 8.44728 -> 8
    ts_rank_adv60 = ts_rank(adv60, window=21)  # 20.6966 -> 21

    corr1 = rolling_corr(ts_rank_close, ts_rank_adv60, window=8)  # 8.01266 -> 8
    decay2 = decay_linear(corr1, window=7)  # 6.65053 -> 7
    part2 = ts_rank(decay2, window=3)  # 2.61957 -> 3

    # Final: element-wise min
    factor = pl.min_horizontal([part1, part2])

    return df.select(factor).to_series()